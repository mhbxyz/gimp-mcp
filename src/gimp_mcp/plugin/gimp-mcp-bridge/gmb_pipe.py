"""Windows named-pipe transport of the bridge (#100, ADR 0008). Stdlib only (ctypes); Windows only.

Neither GIMP's Python nor the server's CPython has AF_UNIX on Windows, so the plug-in serves a named
pipe instead. Only the current user may connect:

* the pipe's DACL grants access to the current user's SID only (protected, no inherited entries);
* ``PIPE_REJECT_REMOTE_CLIENTS`` refuses clients from other machines;
* ``FILE_FLAG_FIRST_PIPE_INSTANCE`` makes creation fail if another process already owns the name;
* every client's process owner is compared with the current user (the Windows analogue of the
  Unix peer uid check), and the token handshake is unchanged.

Reads block in a thread per client; the bytes are handed to the protocol core on GIMP's main
thread through ``schedule`` (GLib.idle_add in GIMP), so GIMP is only called from its main thread.
"""

import ctypes
import os
import threading
from ctypes import wintypes

PIPE_ACCESS_DUPLEX = 0x00000003
FILE_FLAG_OVERLAPPED = 0x40000000  # reads and writes may be pending at the same time
FILE_FLAG_FIRST_PIPE_INSTANCE = 0x00080000
PIPE_REJECT_REMOTE_CLIENTS = 0x00000008
PIPE_UNLIMITED_INSTANCES = 255
BUFFER = 65536
ERROR_ACCESS_DENIED = 5
ERROR_BROKEN_PIPE = 109
ERROR_PIPE_NOT_CONNECTED = 233
ERROR_MORE_DATA = 234
ERROR_PIPE_CONNECTED = 535
ERROR_OPERATION_ABORTED = 995
ERROR_IO_PENDING = 997
TOKEN_QUERY = 0x0008
TOKEN_USER_CLASS = 1
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
SDDL_REVISION_1 = 1

_kernel32 = None
_advapi32 = None


def _dlls():
    """kernel32 and advapi32 with full prototypes: handles are pointer-sized, never C ints."""
    global _kernel32, _advapi32
    if _kernel32 is None:
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        a = ctypes.WinDLL("advapi32", use_last_error=True)
        H, D, B, P = wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL, ctypes.c_void_p
        pd = ctypes.POINTER(wintypes.DWORD)
        protos = {
            (k, "CreateNamedPipeW"): (H, [wintypes.LPCWSTR, D, D, D, D, D, D, P]),
            (k, "ConnectNamedPipe"): (B, [H, P]),
            (k, "DisconnectNamedPipe"): (B, [H]),
            (k, "CloseHandle"): (B, [H]),
            (k, "CancelIoEx"): (B, [H, P]),
            (k, "CreateEventW"): (H, [P, B, B, wintypes.LPCWSTR]),
            (k, "ReadFile"): (B, [H, P, D, pd, P]),
            (k, "WriteFile"): (B, [H, P, D, pd, P]),
            (k, "GetOverlappedResult"): (B, [H, P, pd, B]),
            (k, "OpenProcess"): (H, [D, B, D]),
            (k, "GetCurrentProcess"): (H, []),
            (k, "LocalFree"): (P, [P]),
            (k, "GetNamedPipeClientProcessId"): (B, [H, ctypes.POINTER(wintypes.ULONG)]),
            (k, "GetNamedPipeServerProcessId"): (B, [H, ctypes.POINTER(wintypes.ULONG)]),
            (a, "OpenProcessToken"): (B, [H, D, ctypes.POINTER(H)]),
            (a, "GetTokenInformation"): (B, [H, ctypes.c_int, P, D, pd]),
            (a, "ConvertSidToStringSidW"): (B, [P, ctypes.POINTER(wintypes.LPWSTR)]),
            (a, "ConvertStringSidToSidW"): (B, [wintypes.LPCWSTR, ctypes.POINTER(P)]),
            (a, "ConvertStringSecurityDescriptorToSecurityDescriptorW"): (
                B,
                [wintypes.LPCWSTR, D, ctypes.POINTER(P), P],
            ),
            (a, "GetSecurityInfo"): (D, [H, ctypes.c_int, D, P, P, ctypes.POINTER(P), P, ctypes.POINTER(P)]),
            (a, "ConvertSecurityDescriptorToStringSecurityDescriptorW"): (
                B,
                [P, D, D, ctypes.POINTER(wintypes.LPWSTR), pd],
            ),
        }
        for (dll, name), (restype, argtypes) in protos.items():
            function = getattr(dll, name)
            function.restype, function.argtypes = restype, argtypes
        _kernel32, _advapi32 = k, a
    return _kernel32, _advapi32


INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


class OVERLAPPED(ctypes.Structure):
    _fields_ = [
        ("Internal", ctypes.c_void_p),
        ("InternalHigh", ctypes.c_void_p),
        ("Offset", wintypes.DWORD),
        ("OffsetHigh", wintypes.DWORD),
        ("hEvent", wintypes.HANDLE),
    ]


def _overlapped_call(handle, start):
    """Run an overlapped I/O call and wait for it. Returns (ok, bytes transferred, error code)."""
    kernel32, _ = _dlls()
    event = kernel32.CreateEventW(None, True, False, None)
    if not event:
        raise _error("CreateEventW")
    overlapped = OVERLAPPED(hEvent=event)
    try:
        if start(ctypes.byref(overlapped)):
            code = 0
        else:
            code = ctypes.get_last_error()
            if code != ERROR_IO_PENDING:
                return False, 0, code
        done = wintypes.DWORD()
        if not kernel32.GetOverlappedResult(wintypes.HANDLE(handle), ctypes.byref(overlapped), ctypes.byref(done),
                                            True):  # fmt: skip
            return False, done.value, ctypes.get_last_error()
        return True, done.value, 0
    finally:
        kernel32.CloseHandle(event)


class SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("nLength", wintypes.DWORD),
        ("lpSecurityDescriptor", wintypes.LPVOID),
        ("bInheritHandle", wintypes.BOOL),
    ]


def _error(what):
    code = ctypes.get_last_error()
    return OSError(code, "%s failed: %s" % (what, ctypes.FormatError(code).strip()))


def process_user_sid(pid=None):
    """The string SID of the user owning process ``pid`` (the current process when None)."""
    kernel32, advapi32 = _dlls()
    if pid is None:
        process = kernel32.GetCurrentProcess()
        owned = False
    else:
        process = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not process:
            raise _error("OpenProcess")
        owned = True
    token = wintypes.HANDLE()
    try:
        if not advapi32.OpenProcessToken(process, TOKEN_QUERY, ctypes.byref(token)):
            raise _error("OpenProcessToken")
        size = wintypes.DWORD()
        advapi32.GetTokenInformation(token, TOKEN_USER_CLASS, None, 0, ctypes.byref(size))
        buffer = ctypes.create_string_buffer(size.value)
        if not advapi32.GetTokenInformation(token, TOKEN_USER_CLASS, buffer, size, ctypes.byref(size)):
            raise _error("GetTokenInformation")
        sid = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0]  # TOKEN_USER.User.Sid
        text = wintypes.LPWSTR()
        if not advapi32.ConvertSidToStringSidW(sid, ctypes.byref(text)):
            raise _error("ConvertSidToStringSidW")
        try:
            return text.value
        finally:
            kernel32.LocalFree(ctypes.cast(text, ctypes.c_void_p))
    finally:
        if token:
            kernel32.CloseHandle(token)
        if owned:
            kernel32.CloseHandle(process)


def canonical_sid(text):
    """A SID as S-1-... text, whatever its SDDL spelling (e.g. 'LA' for the built-in Administrator)."""
    kernel32, advapi32 = _dlls()
    sid = ctypes.c_void_p()
    if not advapi32.ConvertStringSidToSidW(text, ctypes.byref(sid)):
        raise _error("ConvertStringSidToSidW")
    try:
        out = wintypes.LPWSTR()
        if not advapi32.ConvertSidToStringSidW(sid, ctypes.byref(out)):
            raise _error("ConvertSidToStringSidW")
        try:
            return out.value
        finally:
            kernel32.LocalFree(ctypes.cast(out, ctypes.c_void_p))
    finally:
        kernel32.LocalFree(sid)


def owner_only_security(sid):
    """SECURITY_ATTRIBUTES whose DACL grants access to ``sid`` only. Keep the returned object alive."""
    _kernel32, advapi32 = _dlls()
    descriptor = ctypes.c_void_p()
    sddl = "D:P(A;;GA;;;%s)" % sid
    if not advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
        sddl, SDDL_REVISION_1, ctypes.byref(descriptor), None
    ):
        raise _error("ConvertStringSecurityDescriptorToSecurityDescriptorW")
    return SECURITY_ATTRIBUTES(ctypes.sizeof(SECURITY_ATTRIBUTES), descriptor, False)


def dacl_sddl(handle):
    """The DACL of a kernel object (e.g. a pipe), as SDDL text."""
    kernel32, advapi32 = _dlls()
    descriptor = ctypes.c_void_p()
    dacl = ctypes.c_void_p()
    # SE_KERNEL_OBJECT = 6, DACL_SECURITY_INFORMATION = 4
    code = advapi32.GetSecurityInfo(handle, 6, 4, None, None, ctypes.byref(dacl), None, ctypes.byref(descriptor))
    if code:
        raise OSError(code, "GetSecurityInfo failed")
    text = wintypes.LPWSTR()
    try:
        if not advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW(descriptor, SDDL_REVISION_1, 4,
                                                                             ctypes.byref(text), None):  # fmt: skip
            raise _error("ConvertSecurityDescriptorToStringSecurityDescriptorW")
        return text.value
    finally:
        kernel32.LocalFree(descriptor)
        if text:
            kernel32.LocalFree(ctypes.cast(text, ctypes.c_void_p))


def client_process_id(handle):
    kernel32, _ = _dlls()
    pid = wintypes.ULONG()
    if not kernel32.GetNamedPipeClientProcessId(wintypes.HANDLE(handle), ctypes.byref(pid)):
        raise _error("GetNamedPipeClientProcessId")
    return pid.value


def server_process_id(handle):
    kernel32, _ = _dlls()
    pid = wintypes.ULONG()
    if not kernel32.GetNamedPipeServerProcessId(wintypes.HANDLE(handle), ctypes.byref(pid)):
        raise _error("GetNamedPipeServerProcessId")
    return pid.value


class PipeConnection:
    """One connected pipe instance, with the subset of the socket API the protocol core uses."""

    def __init__(self, handle):
        self.handle = handle
        self._write_lock = threading.Lock()
        self.closed = False

    def fileno(self):
        return int(self.handle)

    def recv(self, size):
        kernel32, _ = _dlls()
        buffer = ctypes.create_string_buffer(size)
        ok, read, code = _overlapped_call(
            self.handle, lambda ov: kernel32.ReadFile(wintypes.HANDLE(self.handle), buffer, size, None, ov)
        )
        if ok or code == ERROR_MORE_DATA:
            return buffer.raw[:read]
        if code in (ERROR_BROKEN_PIPE, ERROR_PIPE_NOT_CONNECTED, ERROR_OPERATION_ABORTED) or self.closed:
            return b""
        raise OSError(code, ctypes.FormatError(code).strip())

    def sendall(self, data):
        kernel32, _ = _dlls()
        with self._write_lock:
            view = bytes(data)
            while view:
                chunk = view
                ok, written, code = _overlapped_call(
                    self.handle,
                    lambda ov, chunk=chunk: kernel32.WriteFile(
                        wintypes.HANDLE(self.handle), chunk, len(chunk), None, ov
                    ),
                )
                if not ok:
                    raise OSError(code, "WriteFile failed: %s" % ctypes.FormatError(code).strip())
                view = view[written:]

    def settimeout(self, _value):
        pass

    def setblocking(self, _flag):
        pass

    def close(self):
        if self.closed:
            return
        self.closed = True
        kernel32, _ = _dlls()
        kernel32.CancelIoEx(wintypes.HANDLE(self.handle), None)  # ends a pending read in the reader thread
        kernel32.DisconnectNamedPipe(wintypes.HANDLE(self.handle))
        kernel32.CloseHandle(wintypes.HANDLE(self.handle))


class PipeListener:
    """Creates the pipe's instances; the first creation fails if another process owns the name."""

    def __init__(self, name, sid):
        self.name = name
        self.security = owner_only_security(sid)
        self.first = True
        self.closed = False
        self.pending = None

    def create_instance(self):
        kernel32, _ = _dlls()
        flags = PIPE_ACCESS_DUPLEX | FILE_FLAG_OVERLAPPED | (FILE_FLAG_FIRST_PIPE_INSTANCE if self.first else 0)
        handle = kernel32.CreateNamedPipeW(self.name, flags, PIPE_REJECT_REMOTE_CLIENTS, PIPE_UNLIMITED_INSTANCES,
                                           BUFFER, BUFFER, 0, ctypes.byref(self.security))  # fmt: skip
        if handle in (None, INVALID_HANDLE_VALUE):
            code = ctypes.get_last_error()
            if self.first and code == ERROR_ACCESS_DENIED:
                raise OSError(code, "another process already serves %s" % self.name)
            raise OSError(code, "CreateNamedPipeW failed: %s" % ctypes.FormatError(code).strip())
        self.first = False
        return handle

    def wait_for_client(self, handle):
        """Block until a client connects to ``handle``."""
        kernel32, _ = _dlls()
        self.pending = handle
        try:
            ok, _done, code = _overlapped_call(
                handle, lambda ov: kernel32.ConnectNamedPipe(wintypes.HANDLE(handle), ov)
            )
        finally:
            self.pending = None
        if not ok and code != ERROR_PIPE_CONNECTED:
            kernel32.CloseHandle(wintypes.HANDLE(handle))
            raise OSError(code, "ConnectNamedPipe failed: %s" % ctypes.FormatError(code).strip())

    def close(self):
        """Stop accepting: cancel the pending ConnectNamedPipe."""
        self.closed = True
        kernel32, _ = _dlls()
        pending = self.pending
        if pending is not None:
            kernel32.CancelIoEx(wintypes.HANDLE(pending), None)


def serve(server, schedule, allowed_sid, log):
    """Accept clients on ``server.socket_path`` (a pipe name) in a background thread.

    ``schedule(fn, *args)`` must run ``fn`` on the thread that owns ``server`` (GIMP's main thread).
    Returns the listener (close it to stop).
    """
    listener = PipeListener(server.socket_path, allowed_sid)
    first = listener.create_instance()  # raises if another bridge owns the name

    def read_loop(conn):
        while True:
            try:
                chunk = conn.sock.recv(BUFFER)
            except OSError as exc:
                log("pipe read failed: %s" % exc)
                chunk = b""
            if not chunk:
                schedule(server.drop, conn)
                return
            schedule(_feed, server, conn, chunk)

    def accept_loop():
        handle = first
        while not listener.closed:
            try:
                if handle is None:
                    handle = listener.create_instance()
                listener.wait_for_client(handle)
            except OSError as exc:
                if listener.closed:
                    return
                log("pipe accept failed: %s" % exc)
                handle = None
                continue
            if listener.closed:
                PipeConnection(handle).close()
                return
            transport = PipeConnection(handle)
            try:  # the next client must find a free instance while this one is verified and registered
                handle = listener.create_instance()
            except OSError as exc:
                log("cannot create the next pipe instance: %s" % exc)
                handle = None
            try:
                peer = process_user_sid(client_process_id(transport.handle))
            except OSError as exc:
                peer = None
                log("cannot identify pipe client: %s" % exc)
            if peer != allowed_sid:  # an unidentified client is refused too
                log("rejected pipe client of user %s" % peer)
                transport.close()
                continue
            ready = threading.Event()
            holder = {}

            def register(transport=transport, holder=holder, ready=ready):
                holder["conn"] = server.add_connection(transport, None)
                ready.set()

            schedule(register)
            ready.wait()
            threading.Thread(target=read_loop, args=(holder["conn"],), daemon=True).start()

    threading.Thread(target=accept_loop, name="gimp-mcp-pipe", daemon=True).start()
    return listener


def _feed(server, conn, chunk):
    if not getattr(conn, "dropped", False):
        server.handle_data(conn, chunk)


def write_token(path, token):
    """Write the token file in the user's private local application data folder."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="ascii") as handle:
        handle.write(token)
