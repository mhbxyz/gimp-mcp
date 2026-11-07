import pytest

from gimp_mcp.errors import GimpMcpError
from gimp_mcp.ids import IdCodec


def test_ids_round_trip_within_the_same_session():
    codec = IdCodec("a1b2c3d4")
    assert codec.image(3) == "image:3@a1b2c3d4"
    assert codec.item(12) == "item:12@a1b2c3d4"
    assert codec.parse_image("image:3@a1b2c3d4") == 3
    assert codec.parse_item("item:12@a1b2c3d4") == 12


def test_id_from_a_previous_gimp_session_is_rejected():
    codec = IdCodec("newsess1")
    with pytest.raises(GimpMcpError) as excinfo:
        codec.parse_image("image:3@a1b2c3d4")
    assert excinfo.value.code == "SESSION_CHANGED"


@pytest.mark.parametrize("bad", ["3", "image:x@a1b2c3d4", "item:3@a1b2c3d4", "image:-1@a1b2c3d4", ""])
def test_malformed_or_wrong_kind_image_id_is_rejected(bad):
    codec = IdCodec("a1b2c3d4")
    with pytest.raises(GimpMcpError) as excinfo:
        codec.parse_image(bad)
    assert excinfo.value.code == "INVALID_ID"


def test_filter_ids_round_trip():
    codec = IdCodec("a1b2c3d4")
    assert codec.parse_filter(codec.filter(4)) == 4
    with pytest.raises(GimpMcpError):
        codec.parse_filter("item:4@a1b2c3d4")
