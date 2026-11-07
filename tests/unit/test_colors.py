import pytest

from gimp_mcp.colors import parse_color
from gimp_mcp.errors import GimpMcpError


@pytest.mark.parametrize(
    ("text", "rgba"),
    [
        ("#ff0000", (1.0, 0.0, 0.0, 1.0)),
        ("#FF000080", (1.0, 0.0, 0.0, 128 / 255)),
        ("#0f0", (0.0, 1.0, 0.0, 1.0)),
        ("white", (1.0, 1.0, 1.0, 1.0)),
        ("black", (0.0, 0.0, 0.0, 1.0)),
        ("transparent", (0.0, 0.0, 0.0, 0.0)),
    ],
)
def test_colors_are_parsed_to_rgba_floats(text, rgba):
    assert parse_color(text).as_tuple() == pytest.approx(rgba)


@pytest.mark.parametrize("bad", ["", "red-ish", "#12", "#gggggg", "rgb(1,2,3)"])
def test_invalid_colors_are_rejected(bad):
    with pytest.raises(GimpMcpError) as excinfo:
        parse_color(bad)
    assert excinfo.value.code == "INVALID_ARGUMENT"
