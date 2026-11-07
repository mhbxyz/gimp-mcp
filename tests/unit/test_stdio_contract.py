"""The server process speaks MCP on stdout only; logs and diagnostics go to stderr."""

from __future__ import annotations

import json
import subprocess
import sys
import time

from mcp import Client, StdioServerParameters

from .fake_bridge import short_tmpdir


def _messages(*items: dict) -> bytes:
    return b"".join(json.dumps(item).encode() + b"\n" for item in items)


def test_stdout_carries_only_json_rpc_and_logs_go_to_stderr():
    directory = short_tmpdir()
    requests = _messages(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "gimp_status", "arguments": {}},
        },
    )
    started = time.monotonic()
    proc = subprocess.run(
        [sys.executable, "-m", "gimp_mcp", "serve", "--verbose", "--socket", str(directory / "none.sock")],
        input=requests,
        capture_output=True,
        timeout=30,
    )
    directory.rmdir()
    assert time.monotonic() - started < 20
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    assert lines, proc.stderr.decode()
    responses = [json.loads(line) for line in lines]  # every stdout line is JSON
    assert all(message.get("jsonrpc") == "2.0" for message in responses)
    call = next(message for message in responses if message.get("id") == 2)
    assert call["result"]["isError"] is True
    assert call["result"]["structuredContent"]["error"]["code"] == "GIMP_NOT_RUNNING"
    assert b"gimp_status" in proc.stderr  # verbose logs are on stderr


async def test_real_stdio_client_gets_structured_error_when_gimp_is_absent():
    directory = short_tmpdir()
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "gimp_mcp", "serve", "--socket", str(directory / "none.sock")],
    )
    async with Client(params, read_timeout_seconds=30) as client:
        result = await client.call_tool("gimp_status", {})
    directory.rmdir()
    assert result.is_error
    assert result.structured_content is not None
    assert result.structured_content["error"]["code"] == "GIMP_NOT_RUNNING"
