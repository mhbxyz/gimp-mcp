"""#173: every EXIF orientation is read back, on every OS. GIMP 3.2.6 on Windows loaded, in some sessions,
JPEGs with almost none of their Exif: three GIMP sessions open the same twenty files."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from gimp_mcp.headless import HeadlessGimp

from .conftest import mcp_client
from .helpers import call

ORIENTATION = "Exif.Image.Orientation"
INTERPRETED = {6: "right, top", 8: "left, bottom"}


def oriented(folder: Path, count: int) -> list[tuple[Path, int]]:
    files = []
    for index in range(count):
        value = 6 if index % 2 == 0 else 8
        exif = Image.Exif()
        exif[0x0112] = value
        path = folder / f"photo-{index:02d}.jpg"
        Image.new("RGB", (60 + index, 40), (200, 100, 50)).save(path, exif=exif, quality=90)
        files.append((path, value))
    return files


async def test_twenty_oriented_jpegs_keep_their_orientation_in_every_session(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("LANG", "C.UTF-8")  # interpreted values in English
    files = oriented(tmp_path, 20)
    wrong: list[str] = []
    for session in range(3):
        gimp = HeadlessGimp()
        gimp.start()
        try:
            async with mcp_client(gimp) as client:
                for path, value in files:
                    image = await call(client, "gimp_open_image", path=str(path))
                    metadata = await call(client, "gimp_get_metadata", image=image["id"])
                    got = metadata["exif"].get(ORIENTATION)
                    # interpreted ("right, top"), or the number when GIMP cannot interpret it
                    if got not in (INTERPRETED[value], str(value)) or image["dirty"]:
                        wrong.append(
                            f"session {session} {path.name}: {got!r}, dirty={image['dirty']}, "
                            f"exif {sorted(metadata['exif'])}"
                        )
                    await call(client, "gimp_close_image", image=image["id"], discard_changes=True)
        finally:
            gimp.stop()
            if wrong:  # what the plug-in saw (its log lines about Exif), for the failure report
                log = gimp.log_path.read_text(encoding="utf-8", errors="replace") if gimp.log_path.exists() else ""
                wrong += [line for line in log.splitlines() if "Exif" in line or "orientation" in line][:12]
    assert wrong == []


async def test_a_removed_orientation_stays_removed(gimp: HeadlessGimp, tmp_path: Path):
    [(path, _value)] = oriented(tmp_path, 1)
    async with mcp_client(gimp) as client:
        image = (await call(client, "gimp_open_image", path=str(path)))["id"]
        removed = await call(client, "gimp_set_metadata", image=image, remove=[ORIENTATION])
        again = await call(client, "gimp_get_metadata", image=image)
        await call(client, "gimp_close_image", image=image, discard_changes=True)
    assert ORIENTATION not in removed["exif"] and ORIENTATION not in again["exif"]
