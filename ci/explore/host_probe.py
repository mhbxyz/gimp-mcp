# Runs on the runner's own CPython (the MCP server side).
import json, os, socket, sys, asyncio
facts = {"python": sys.version, "platform": sys.platform, "has_AF_UNIX": hasattr(socket, "AF_UNIX"),
         "has_LOCAL_PEERCRED": hasattr(socket, "LOCAL_PEERCRED"), "open_unix_connection": hasattr(asyncio, "open_unix_connection")}
try:
    import _winapi
    facts["_winapi_pipes"] = [n for n in dir(_winapi) if "Pipe" in n]
except ImportError:
    facts["_winapi_pipes"] = None
print(json.dumps(facts, indent=2))
