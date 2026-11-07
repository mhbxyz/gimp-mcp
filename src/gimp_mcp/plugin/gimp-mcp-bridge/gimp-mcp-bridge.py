#!/usr/bin/env python3
"""gimp-mcp bridge: a persistent GIMP 3 plug-in serving a local Unix socket.

GIMP starts this plug-in automatically at launch (a PERSISTENT procedure
without arguments is an "extension"), in the GUI as well as in gimp-console.
It stays alive until GIMP quits. All GIMP API calls happen on the plug-in's
main thread from a GLib main loop, one request at a time.
"""

import os
import secrets
import sys

import gi

gi.require_version("Gimp", "3.0")
from gi.repository import Gimp, GLib  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import gmb_server  # noqa: E402

try:  # PyGObject >= 3.52 moved Unix helpers to GLibUnix
    gi.require_version("GLibUnix", "2.0")
    from gi.repository import GLibUnix

    fd_add_full = GLibUnix.fd_add_full
except (ImportError, ValueError, AttributeError):
    fd_add_full = GLib.unix_fd_add_full

PROCEDURE = "extension-gimp-mcp-bridge"
BRIDGE_VERSION = "0.1.0"


def run_bridge(procedure, config, data):
    procedure.persistent_ready()
    plug_in = procedure.get_plug_in()
    socket_path = gmb_server.default_socket_path(os.environ)
    try:
        import gmb_ops

        operations = gmb_ops.build_operations()
        session_id = gmb_server.gimp_session_id()
        gmb_ops.SESSION["id"] = session_id
        server = gmb_server.BridgeServer(
            socket_path,
            token=secrets.token_hex(32),
            operations=operations,
            session_info={
                "gimp_version": Gimp.version(),
                "session_id": session_id,
                "pid": os.getppid(),
                "bridge_version": BRIDGE_VERSION,
            },
        )
        server.start()
    except Exception as exc:  # keep GIMP usable even if the bridge cannot start
        gmb_server.log("bridge disabled: %s" % exc)
        while True:
            plug_in.persistent_process(0)

    loop = GLib.MainLoop()
    plug_in.persistent_enable()
    condition = GLib.IOCondition.IN | GLib.IOCondition.HUP | GLib.IOCondition.ERR

    def on_client(fd, cond, conn):
        if cond & (GLib.IOCondition.HUP | GLib.IOCondition.ERR) and not cond & GLib.IOCondition.IN:
            server.drop(conn)
            return False
        return server.handle_readable(conn)

    def on_accept(fd, cond):
        conn = server.handle_accept()
        if conn is not None:
            fd_add_full(GLib.PRIORITY_DEFAULT, conn.fileno(), condition, on_client, conn)
        return True

    fd_add_full(GLib.PRIORITY_DEFAULT, server.fileno(), GLib.IOCondition.IN, on_accept)
    try:
        loop.run()
    finally:
        server.close()
    return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, None)


class GimpMcpBridge(Gimp.PlugIn):
    def do_set_i18n(self, name):
        return False

    def do_query_procedures(self):
        return [PROCEDURE]

    def do_create_procedure(self, name):
        procedure = Gimp.Procedure.new(self, name, Gimp.PDBProcType.PERSISTENT, run_bridge, None)
        procedure.set_documentation(
            "gimp-mcp bridge",
            "Serves the gimp-mcp Model Context Protocol server over a local Unix socket.",
            name,
        )
        procedure.set_attribution("gimp-mcp contributors", "gimp-mcp contributors", "2026")
        return procedure


Gimp.main(GimpMcpBridge.__gtype__, sys.argv)
