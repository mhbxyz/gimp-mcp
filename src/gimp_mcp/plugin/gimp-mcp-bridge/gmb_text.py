"""Rich text markup (#56): GIMP text layers take a subset of Pango markup. Stdlib only, no GIMP.

The markup is checked before GIMP sees it: well-formed XML, known tags and attributes only.
"""

import re
import xml.etree.ElementTree as ET

SIMPLE_TAGS = {"b", "i", "u", "s", "big", "small", "sub", "sup", "tt"}
SPAN_ATTRIBUTES = {
    "font", "font_family", "face", "size", "style", "weight", "variant", "stretch", "foreground", "fgcolor",
    "color", "background", "bgcolor", "underline", "underline_color", "strikethrough", "strikethrough_color",
    "rise", "letter_spacing", "lang", "font_features", "alpha", "fgalpha",
}  # fmt: skip
COLOR_ATTRIBUTES = {"foreground", "fgcolor", "color", "background", "bgcolor", "underline_color", "strikethrough_color"}
COLOR = re.compile(r"^#[0-9a-fA-F]{3,12}$|^[A-Za-z]{3,30}$")


def check_markup(markup):
    """Returns the markup unchanged, or raises ValueError explaining what is wrong."""
    try:
        root = ET.fromstring("<markup>%s</markup>" % markup)
    except ET.ParseError as error:
        raise ValueError("markup is not well-formed XML: %s" % error) from None
    for element in root.iter():
        if element is root:
            continue
        if element.tag != "span" and element.tag not in SIMPLE_TAGS:
            raise ValueError("tag <%s> is not allowed (use span, %s)" % (element.tag, ", ".join(sorted(SIMPLE_TAGS))))
        for name, value in element.attrib.items():
            if element.tag != "span" or name not in SPAN_ATTRIBUTES:
                raise ValueError("attribute %r is not allowed on <%s>" % (name, element.tag))
            if name in COLOR_ATTRIBUTES and not COLOR.match(value):
                raise ValueError("%s=%r is not a color" % (name, value))
    return markup
