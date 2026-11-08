"""File formats (#58): export procedure choice and behaviour. Standard library only, no GIMP."""

# Arguments every export procedure has, set by the bridge itself; metadata flags follow the
# `metadata` export option (nothing unless asked, see #60).
FIXED_ARGUMENTS = {"run-mode", "image", "file", "options"}
METADATA_ARGUMENTS = {
    "include-exif", "include-iptc", "include-xmp", "include-thumbnail", "include-comment", "include-color-profile",
}  # fmt: skip

# What each export keeps. "lossless": None when it depends on the image (palette reduction, vector
# content); "layers": flattened (one image), kept (layers stay layers), frames (animation), pages
# (one page per layer), sizes (one icon size per layer).
BEHAVIOUR = {
    "file-png-export": (True, "flattened"),
    "file-jpeg-export": (False, "flattened"),
    "file-webp-export": (False, "flattened"),
    "file-heif-export": (False, "flattened"),
    "file-heif-av1-export": (False, "flattened"),
    "file-jpegxl-export": (False, "flattened"),
    "file-tiff-export": (True, "pages"),
    "file-bmp-export": (True, "flattened"),
    "file-gif-export": (None, "flattened"),
    "file-ico-export": (True, "sizes"),
    "file-psd-export": (True, "kept"),
    "file-openraster-export": (True, "kept"),
    "file-pdf-export": (None, "flattened"),
    "file-qoi-export": (True, "flattened"),
    "file-tga-export": (True, "flattened"),
}


def procedure_for(path, extensions_by_procedure):
    """The export/load procedure whose extension ends the path (longest match, case-insensitive)."""
    lowered = path.lower()
    best, best_length = None, 0
    for procedure, extensions in extensions_by_procedure.items():
        for extension in extensions:
            suffix = "." + extension.lower()
            if lowered.endswith(suffix) and len(suffix) > best_length:
                best, best_length = procedure, len(suffix)
    return best


def behaviour(procedure, options):
    """``options``: the effective values (GIMP's defaults merged with the given ones)."""
    lossless, layers = BEHAVIOUR.get(procedure, (None, None))
    if procedure in ("file-webp-export", "file-heif-export", "file-heif-av1-export", "file-jpegxl-export"):
        lossless = bool(options.get("lossless"))
    if procedure == "file-webp-export" and options.get("animation"):
        layers = "frames"
    if procedure == "file-gif-export" and options.get("as-animation"):
        layers = "frames"
    if procedure == "file-pdf-export" and options.get("layers-as-pages"):
        layers = "pages"
    return {"lossless": lossless, "layers": layers}


def option_names(arguments):
    return [name for name in arguments if name not in FIXED_ARGUMENTS and name not in METADATA_ARGUMENTS]


def layer_filename(template, index, name, extension):
    """File name for a layer export: ``{index}`` and ``{name}`` (made safe for file systems)."""
    safe = "".join(c if c.isalnum() or c in " ._-" else "_" for c in name).strip(" .") or "layer"
    return template.format(index=index, name=safe) + "." + extension


# GIMP 3.2 does not tell plug-ins which extensions another plug-in's file procedure handles:
# they are derived from the procedure name (file-<ext>-export / file-<ext>-load), with these exceptions.
EXTENSION_ALIASES = {
    "jpeg": ["jpg", "jpeg", "jpe"],
    "tiff": ["tif", "tiff"],
    "heif-av1": ["avif"],
    "heif": ["heif", "heic"],
    "jpegxl": ["jxl"],
    "openraster": ["ora"],
    "gz": ["xcf.gz"],
    "bz2": ["xcf.bz2"],
    "xz": ["xcf.xz"],
    "colorxhtml": ["html"],
    "html-table": ["html"],
    "csource": ["c"],
    "header": ["h"],
    "sunras": ["ras"],
    "farbfeld": ["ff"],
    "gih": ["gih"],
}


def extensions_for(procedure):
    for suffix in ("-export", "-load"):
        if procedure.startswith("file-") and procedure.endswith(suffix):
            stem = procedure[len("file-") : -len(suffix)]
            return EXTENSION_ALIASES.get(stem, [stem])
    return []
