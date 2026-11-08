"""Rich text markup validation (#56), without GIMP."""

from __future__ import annotations

import gmb_text  # type: ignore[import-not-found]
import pytest


@pytest.mark.parametrize(
    "markup",
    [
        "plain",
        "<b>bold</b> and <i>italic</i>, <u>under</u> <s>strike</s>",
        '<span font="Sans Bold 24" foreground="#ff0000" letter_spacing="2048" rise="-5000">x</span>',
        '<span size="20480" underline="double" weight="bold" style="italic">y</span>',
        "a &amp; b &lt; c",
    ],
)
def test_valid_markup(markup):
    assert gmb_text.check_markup(markup) == markup


@pytest.mark.parametrize(
    ("markup", "message"),
    [
        ("<b>open", "not well-formed"),
        ("<script>x</script>", "tag <script>"),
        ('<span onclick="x">y</span>', "attribute 'onclick'"),
        ('<span foreground="red; x">y</span>', "foreground"),
        ("a & b", "not well-formed"),
    ],
)
def test_invalid_markup(markup, message):
    with pytest.raises(ValueError, match=message):
        gmb_text.check_markup(markup)
