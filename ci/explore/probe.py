# Runs inside GIMP (python-fu-eval): records facts about GIMP's bundled Python on this OS.
import json, os, socket, sys, tempfile, traceback
facts = {}
def note(key, fn):
    try:
        facts[key] = fn()
    except Exception as error:
        facts[key] = "ERROR: %r" % (error,)
import gi
gi.require_version("Gimp", "3.0")
from gi.repository import Gimp, GLib, Gio
note("python", lambda: sys.version)
note("executable", lambda: sys.executable)
note("platform", lambda: sys.platform)
note("gi", lambda: gi.__version__)
note("glib", lambda: "%d.%d.%d" % (GLib.MAJOR_VERSION, GLib.MINOR_VERSION, GLib.MICRO_VERSION))
note("gimp", lambda: Gimp.version())
note("gimp_directory", lambda: Gimp.directory())
note("plug_in_directory", lambda: Gimp.plug_in_directory())
note("data_directory", lambda: Gimp.data_directory())
note("has_AF_UNIX", lambda: hasattr(socket, "AF_UNIX"))
note("has_SO_PEERCRED", lambda: hasattr(socket, "SO_PEERCRED"))
note("has_LOCAL_PEERCRED", lambda: hasattr(socket, "LOCAL_PEERCRED"))
note("has_getuid", lambda: hasattr(os, "getuid"))
note("unix_fd_add_full", lambda: hasattr(GLib, "unix_fd_add_full"))
note("io_add_watch", lambda: hasattr(GLib, "io_add_watch"))
def unix_bind():
    path = os.path.join(tempfile.mkdtemp(), "s.sock")
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.bind(path); s.listen(1)
    c = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); c.connect(path)
    a, _ = s.accept(); c.sendall(b"hi"); data = a.recv(2)
    return "ok %r" % data
note("python_af_unix_roundtrip", unix_bind)
def gio_unix():
    path = os.path.join(tempfile.mkdtemp(), "g.sock")
    addr = Gio.UnixSocketAddress.new(path)
    service = Gio.SocketService.new()
    service.add_address(addr, Gio.SocketType.STREAM, Gio.SocketProtocol.DEFAULT, None)
    return "listening at %s" % path
note("gio_unix_listen", gio_unix)
def winapi():
    import _winapi
    return [n for n in dir(_winapi) if "Pipe" in n]
note("_winapi", winapi)
def ctypes_ok():
    import ctypes
    return str(ctypes.sizeof(ctypes.c_void_p))
note("ctypes", ctypes_ok)
note("env_GIMP3_DIRECTORY", lambda: os.environ.get("GIMP3_DIRECTORY"))
note("env_tmp", lambda: tempfile.gettempdir())
note("env_XDG_RUNTIME_DIR", lambda: os.environ.get("XDG_RUNTIME_DIR"))
out = os.environ.get("PROBE_OUT", "probe.json")
with open(out, "w") as handle:
    json.dump(facts, handle, indent=2)
