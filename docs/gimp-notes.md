# GIMP 3 behaviour notes (verified, not assumed)

Each entry was observed on GIMP 3.2.6 / PyGObject 3.58 / Python 3.14 (Arch).

## Plug-ins and lifecycle

* A `Gimp.Procedure` of type `PERSISTENT` with **no arguments** is started
  automatically at GIMP launch, both in the GUI (`gimp`) and in
  `gimp-console -i`. It must call `procedure.persistent_ready()`.
* After `plug_in.persistent_enable()`, a `GLib.MainLoop` in the plug-in keeps
  servicing GIMP's messages; GIMP's quit terminates the plug-in cleanly.
* `GLib.unix_fd_add_full` is deprecated in PyGObject ≥ 3.52; use
  `GLibUnix.fd_add_full`.
* Python plug-ins run through `#!/usr/bin/env python3`. If GIMP inherits a
  `PATH` whose first `python3` is a virtualenv without PyGObject, *every*
  Python plug-in fails with `ModuleNotFoundError: No module named 'gi'`.
* `gimp-console` without `--quit` stays running in the background until
  SIGTERM/SIGINT.
* Files passed on the command line are opened *after* extensions start: the
  bridge may answer before they are listed by `Gimp.get_images()`.
* `GIMP3_DIRECTORY` replaces the whole user configuration directory (used for
  isolated tests).
* Startup time of `gimp-console -i`: ≈0.8 s with `--no-data --no-fonts`, ≈5 s
  with fonts and data.

## API facts

* There is **no PDB procedure or libgimp function to undo/redo**. Only
  `gimp-image-undo-group-start/end`, `-disable/-enable`, `-freeze/-thaw` and
  `-is-enabled` exist (PDB dump of 3.2.6).
* `Gimp.Image.get_name()` is a localized display name, e.g.
  `"[photo] (importée)"` for an imported PNG.
* AF_UNIX socket paths longer than ~107 bytes fail with `OSError: AF_UNIX path
  too long`.
