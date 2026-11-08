"""Nothing in GIMP's process tree (GIMP, its plug-ins, the bridge) listens on a network socket (ADR 0008).

Listening means a TCP socket in the LISTEN state or a bound UDP socket. Outgoing connections are not
listening (GIMP itself checks for updates over HTTPS).

The bridge is a Unix socket (Linux, macOS) or a named pipe (Windows); this checks it from the OS side,
with each OS's own view of sockets, once the bridge has answered.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

from gimp_mcp import platforms
from gimp_mcp.headless import HeadlessGimp


def process_tree(root: int) -> set[int]:
    """root and all its descendants."""
    if platforms.CURRENT == "windows":
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId | ConvertTo-Json"],
            capture_output=True, text=True, check=True,
        ).stdout  # fmt: skip
        pairs = [(p["ProcessId"], p["ParentProcessId"]) for p in json.loads(out)]
    else:
        out = subprocess.run(["ps", "-A", "-o", "pid=,ppid="], capture_output=True, text=True, check=True).stdout
        pairs = [tuple(int(v) for v in line.split()) for line in out.splitlines() if line.strip()]
    children: dict[int, list[int]] = {}
    for pid, ppid in pairs:
        children.setdefault(ppid, []).append(pid)
    tree, todo = set(), [root]
    while todo:
        pid = todo.pop()
        if pid not in tree:
            tree.add(pid)
            todo.extend(children.get(pid, []))
    return tree


def network_sockets(pids: set[int]) -> list[str]:
    """Listening network sockets (TCP in LISTEN, UDP) owned by these processes, as the OS reports them."""
    if platforms.CURRENT == "windows":
        ids = ",".join(str(p) for p in pids)
        script = (
            f"$ids = @({ids}); "
            "Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue "
            "| Where-Object { $ids -contains $_.OwningProcess } "
            "| ForEach-Object { 'tcp ' + $_.LocalAddress + ':' + $_.LocalPort + ' ' + $_.State }; "
            "Get-NetUDPEndpoint -ErrorAction SilentlyContinue | Where-Object { $ids -contains $_.OwningProcess } "
            "| ForEach-Object { 'udp ' + $_.LocalAddress + ':' + $_.LocalPort }"
        )
        out = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, text=True)
        return [line for line in out.stdout.splitlines() if line.strip()]
    if platforms.CURRENT == "macos":
        found = []
        for selector in (["-iTCP", "-sTCP:LISTEN"], ["-iUDP"]):
            out = subprocess.run(
                ["lsof", "-nP", "-a", "-p", ",".join(str(p) for p in pids), *selector], capture_output=True, text=True
            )
            found += out.stdout.splitlines()[1:]  # header removed; lsof exits 1 when nothing matches
        return found
    inodes: dict[str, str] = {}
    for kind in ("tcp", "tcp6", "udp", "udp6"):
        for line in Path(f"/proc/net/{kind}").read_text(encoding="ascii").splitlines()[1:]:
            fields = line.split()
            if kind.startswith("tcp") and fields[3] != "0A":  # 0A: LISTEN; others are connections
                continue
            inodes[fields[9]] = f"{kind} {fields[1]} state {fields[3]}"
    found = []
    for pid in pids:
        try:
            entries = list(Path(f"/proc/{pid}/fd").iterdir())
        except OSError:
            continue
        for entry in entries:
            try:
                link = os.readlink(entry)
            except OSError:  # closed meanwhile (e.g. the descriptor of the listing itself)
                continue
            match = re.fullmatch(r"socket:\[(\d+)\]", link)
            if match and match.group(1) in inodes:
                found.append(f"pid {pid}: {inodes[match.group(1)]}")
    return found


def test_gimp_and_the_bridge_own_no_network_socket(gimp: HeadlessGimp):
    assert gimp.sync_call("hello")["protocol"] == 1  # the bridge is up and answering
    assert gimp.process is not None
    tree = process_tree(gimp.process.pid)
    assert len(tree) >= 2  # GIMP and at least the bridge plug-in
    assert network_sockets(tree) == []
