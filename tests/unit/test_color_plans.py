"""Color adjustments (#48): mapping of the documented ranges to GIMP's operations, no GIMP."""

from __future__ import annotations

import gmb_color  # type: ignore[import-not-found]
import pytest


def test_levels_map_0_255_to_gimp_fractions():
    op, props = gmb_color.plan(
        "levels",
        {"channel": "red", "input_low": 51, "input_high": 204, "gamma": 2.0, "output_low": 0, "output_high": 255},
    )
    assert op == "gimp:levels"
    assert props == {
        "trc": ("enum", "non-linear"),  # on sRGB values, like GIMP's Levels dialog (the op defaults to linear)
        "channel": ("enum", "red"),
        "low-input": 0.2,
        "high-input": 0.8,
        "gamma": 2.0,
        "low-output": 0.0,
        "high-output": 1.0,
    }


def test_color_balance_colorize_threshold_posterize():
    assert gmb_color.plan(
        "color-balance",
        {"range": "shadows", "cyan_red": 50, "magenta_green": -100, "yellow_blue": 0, "preserve_luminosity": True},
    ) == (
        "gimp:color-balance",
        {"range": ("enum", "shadows"), "cyan-red": 0.5, "magenta-green": -1.0, "yellow-blue": 0.0,
         "preserve-luminosity": True},
    )  # fmt: skip
    # gimp:colorize follows its "color" property (setting hue alone has no effect in GIMP 3.2):
    # the color is HSL(hue, saturation, 50%)
    assert gmb_color.plan("colorize", {"hue": 180, "saturation": 50, "lightness": -25}) == (
        "gimp:colorize",
        {"hue": 0.5, "saturation": 0.5, "lightness": -0.25, "color": ("color", (0.25, 0.75, 0.75, 1.0))},
    )
    assert gmb_color.plan("threshold", {"channel": "value", "low": 128, "high": 255}) == (
        "gimp:threshold",
        {"channel": ("enum", "value"), "low": 128 / 255, "high": 1.0},
    )
    assert gmb_color.plan("posterize", {"levels": 4}) == ("gimp:posterize", {"levels": 4})


def test_desaturate_invert_exposure_shadows_highlights_and_stretch():
    assert gmb_color.plan("desaturate", {"mode": "luma"}) == ("gimp:desaturate", {"mode": ("enum", "luma")})
    assert gmb_color.plan("invert", {"linear": False}) == ("gegl:invert-gamma", {})
    assert gmb_color.plan("invert", {"linear": True}) == ("gegl:invert-linear", {})
    assert gmb_color.plan("exposure", {"exposure": 1.5, "black_level": 0.01}) == (
        "gegl:exposure",
        {"exposure": 1.5, "black-level": 0.01},
    )
    op, props = gmb_color.plan("shadows-highlights", {"shadows": 40, "highlights": -20, "radius": 50})
    assert op == "gegl:shadows-highlights" and props == {"shadows": 40.0, "highlights": -20.0, "radius": 50.0}
    assert gmb_color.plan("stretch-contrast", {"keep_colors": True}) == (
        "gegl:stretch-contrast",
        {"keep-colors": True},
    )


def test_destructive_only_adjustments_have_no_operation():
    assert gmb_color.plan("equalize", {}) == (None, {})
    assert gmb_color.plan("white-balance", {}) == (None, {})


def test_curve_points_and_samples():
    assert gmb_color.curve_points([[0, 0], [128, 200], [255, 255]]) == [0.0, 0.0, 128 / 255, 200 / 255, 1.0, 1.0]
    # GIMP needs >= 256 samples: shorter lists are resampled linearly
    resampled = gmb_color.curve_samples([0, 255])
    assert len(resampled) == 256 and resampled[0] == 0.0 and resampled[-1] == 1.0
    assert resampled[51] == pytest.approx(0.2)
    assert gmb_color.curve_samples([255, 0])[255] == 0.0
    with pytest.raises(ValueError, match="increasing"):
        gmb_color.curve_points([[0, 0], [128, 10], [128, 20]])
    with pytest.raises(ValueError, match="at least 2"):
        gmb_color.curve_points([[0, 0]])


@pytest.mark.parametrize(
    ("adjustment", "settings", "message"),
    [
        ("levels", {"input_low": 200, "input_high": 100}, "input_low must be lower than input_high"),
        ("levels", {"output_low": 300}, "between 0 and 255"),
        ("threshold", {"low": 200, "high": 100}, "low must not exceed high"),
        ("posterize", {"levels": 1}, "between 2 and 256"),
        ("unknown", {}, "unknown adjustment"),
    ],
)
def test_invalid_settings(adjustment, settings, message):
    with pytest.raises(ValueError, match=message):
        gmb_color.plan(adjustment, settings)
