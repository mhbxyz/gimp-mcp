import os

from gimp_mcp.installer import install_plugin, installed_plugin_dir, uninstall_plugin


def test_install_copies_an_executable_plugin_and_uninstall_removes_it(tmp_path):
    target = install_plugin(tmp_path)
    assert target == installed_plugin_dir(tmp_path)
    entry = target / "gimp-mcp-bridge.py"
    assert os.access(entry, os.X_OK)
    assert (target / "gmb_server.py").exists()
    assert not list(target.rglob("__pycache__"))
    assert uninstall_plugin(tmp_path) is True
    assert not target.exists()
    assert uninstall_plugin(tmp_path) is False
