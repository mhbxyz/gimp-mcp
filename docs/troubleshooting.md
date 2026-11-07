# Troubleshooting

<!-- Generated from src/gimp_mcp/doctor.py (CHECKS) by `gimp-mcp doctor --troubleshooting`. -->

Run `gimp-mcp doctor` first: it runs the checks below in order and prints, for each failure or
warning, what it found and how to fix it. `gimp-mcp doctor --json` gives the same result for scripts.

Exit codes: `0` no failure (warnings allowed), `1` at least one failure, `2` the doctor could not run.

| Check | What it verifies | Fix when it fails |
|---|---|---|
| `gimp` | GIMP 3.2 or newer is installed | Install GIMP 3.2 or newer from your distribution (e.g. `sudo pacman -S gimp`); gimp-mcp needs `gimp-console` on PATH or GIMP_MCP_GIMP_CONSOLE pointing to it. |
| `gimp-python` | GIMP's Python can load PyGObject and the GIMP typelib | Install PyGObject for the system Python and GIMP's introspection data (Arch: `python-gobject`; Debian/Ubuntu: `python3-gi gir1.2-gimp-3.0`; Fedora: `python3-gobject`). |
| `venv-path` | No virtualenv shadows the system python3 | Start GIMP from your desktop or from a shell without the virtualenv (`deactivate`): GIMP runs Python plug-ins with the first `python3` on PATH. |
| `profiles` | The plug-in is installed in the GIMP profile actually used | Run `gimp-mcp install-plugin --gimp-dir <profile used by GIMP>` (default ~/.config/GIMP/3.2, or $GIMP3_DIRECTORY). |
| `plugin` | The bridge plug-in is installed and executable | Run `gimp-mcp install-plugin`, then restart GIMP. |
| `plugin-version` | The installed plug-in matches the server version | Run `gimp-mcp install-plugin` with the gimp-mcp you use as MCP server, then restart GIMP. |
| `plugin-registered` | GIMP has registered the plug-in | Restart GIMP. If the plug-in is still not registered, GIMP could not run it: see the gimp-python and venv-path checks, and GIMP's error console. |
| `socket-permissions` | The bridge socket directory and token are private | Restart GIMP to recreate them, or fix them: `chmod 700 <socket dir>` and `chmod 600 <token file>` (they must belong to you). |
| `connection` | A running GIMP answers on the bridge socket | Start GIMP (after `gimp-mcp install-plugin`). If GIMP is already running, restart it so it loads the plug-in. |
| `instances` | Only one GIMP instance competes for the bridge socket | Close the extra GIMP instances, or give each one its own socket with GIMP_MCP_SOCKET (set it for GIMP and for `gimp-mcp serve`). |
