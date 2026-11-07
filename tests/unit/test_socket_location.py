import os

import gmb_server  # type: ignore[import-not-found]

from gimp_mcp.bridge import default_socket_path


def test_plugin_and_server_agree_on_the_socket_location(tmp_path):
    cases = [
        {"GIMP_MCP_SOCKET": "/x/y.sock"},
        {"XDG_RUNTIME_DIR": str(tmp_path)},
        {"XDG_RUNTIME_DIR": "/does/not/exist"},
        {},
    ]
    for env in cases:
        assert str(default_socket_path(env)) == gmb_server.default_socket_path(env)


def test_session_id_is_stable_for_a_process_and_differs_between_processes():
    me = gmb_server.gimp_session_id(os.getpid())
    assert me == gmb_server.gimp_session_id(os.getpid())
    assert me != gmb_server.gimp_session_id(1)
    assert len(me) == 8
