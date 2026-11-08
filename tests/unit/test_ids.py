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


def test_any_of_several_kinds_is_parsed_with_its_kind():
    import pytest as _pytest

    from gimp_mcp.errors import GimpMcpError as _Error

    codec = IdCodec("s1")
    assert codec.parse_any("checkpoint:4@s1", ("image", "item", "checkpoint")) == ("checkpoint", 4)
    assert codec.parse_any("item:9@s1", ("image", "item")) == ("item", 9)
    with _pytest.raises(_Error) as error:
        codec.parse_any("filter:1@s1", ("image", "item"))
    assert error.value.code == "INVALID_ID"
    with _pytest.raises(_Error) as error:
        codec.parse_any("image:1@old", ("image",))
    assert error.value.code == "SESSION_CHANGED"
