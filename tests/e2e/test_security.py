"""What the security review for 1.0 closed (#122), checked on a real GIMP: nothing below writes or reads a
file it should not. docs/security.md links each mitigation to its test."""

from __future__ import annotations

from pathlib import Path

from gimp_mcp.headless import HeadlessGimp

from .conftest import mcp_client
from .helpers import call, error


async def test_a_palette_never_turns_into_a_script(gimp: HeadlessGimp, tmp_path: Path):
    async with mcp_client(gimp) as client:
        palette = await call(client, "gimp_create_resource", kind="palette", name="Injected")
        await call(
            client, "gimp_edit_palette", name=palette["name"],
            entries=[{"color": "#010203", "name": "x\n; touch pwned #"},
                     {"color": "#040506", "name": 'q"); import os'}],
        )  # fmt: skip
        # a gpl file keeps one line per entry: no line of its own for the injected command
        gpl = tmp_path / "out.gpl"
        await call(client, "gimp_export_palette", name=palette["name"], path=str(gpl))
        lines = gpl.read_text().splitlines()
        assert [line for line in lines if "touch pwned" in line] == ["  1   2   3\tx ; touch pwned #"]
        # GIMP's code exports would paste the names into code: refused, nothing written
        for fmt, extension in (("python", "py"), ("css", "css"), ("php", "php"), ("java", "java")):
            refused = await error(
                client, "gimp_export_palette", name=palette["name"], path=str(tmp_path / f"p.{extension}"), format=fmt
            )
            assert refused["code"] == "INVALID_ARGUMENT", fmt
        # and a palette never lands in a file that a shell or the system would run
        for name in (".zshenv", "start.bat"):
            refused = await error(client, "gimp_export_palette", name=palette["name"], path=str(tmp_path / name))
            assert refused["code"] == "INVALID_ARGUMENT", name
        assert sorted(p.name for p in tmp_path.iterdir()) == ["out.gpl"]
        await call(client, "gimp_delete_resource", kind="palette", name=palette["name"])


async def test_procedures_that_read_other_files_are_refused(gimp: HeadlessGimp, tmp_path: Path):
    secret = tmp_path / "id_ed25519"
    secret.write_bytes(b"-----BEGIN OPENSSH PRIVATE KEY-----\n" + bytes(range(256)) * 16)
    async with mcp_client(gimp) as client:
        before = len((await call(client, "gimp_status"))["images"])
        raw = await error(
            client, "gimp_open_with_options", path=str(secret), procedure="file-raw-load",
            options={"width": 64, "height": 64},
        )  # fmt: skip
        assert raw["code"] == "INVALID_ARGUMENT"
        assert len((await call(client, "gimp_status"))["images"]) == before
        image = (await call(client, "gimp_create_image", width=8, height=8, fill="#808080"))["id"]
        page = tmp_path / "page.html"
        copied = await error(
            client, "gimp_export_as", image=image, path=str(page),
            options={"source-file": True, "characters": str(secret)},
        )  # fmt: skip
        assert copied["code"] == "INVALID_ARGUMENT" and not page.exists()
        await call(client, "gimp_close_image", image=image, discard_changes=True)


async def test_each_gimp_session_has_a_new_token(gimp: HeadlessGimp):
    # A token read once (a log, a backup) is useless after GIMP restarts (docs/security.md).
    before = gimp.token_path.read_text(encoding="ascii").strip()
    gimp.restart()
    after = gimp.token_path.read_text(encoding="ascii").strip()
    assert len(after) == 64 and after != before
    async with mcp_client(gimp) as client:
        assert (await call(client, "gimp_status"))["connected"]
