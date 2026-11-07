# ADR 0003 — Support Flatpak GIMP through the app runtime directory

- Status: accepted (2026-11-08)
- Context issue: #41

## Context

Many Linux users install GIMP from Flathub (`org.gimp.GIMP`). Verified on
2026-11-08 with the Flathub build GIMP 3.2.8 (commit `a13ff5e6…`, runtime
`org.gnome.Platform` 51), in a disposable container:

* the app has `--filesystem=xdg-config/GIMP:create`, `host` and `/tmp`: GIMP
  reads **the host profile `~/.config/GIMP/3.2`**, so the plug-in is installed
  exactly as for a native GIMP;
* the sandbox has `/app/bin/gimp-console-3.2`, Python 3.14 and PyGObject with
  the `Gimp-3.0` typelib: Python plug-ins, including the bridge, work and the
  extension auto-starts;
* inside the sandbox `XDG_RUNTIME_DIR` is private, except
  `$XDG_RUNTIME_DIR/app/org.gimp.GIMP`, which Flatpak creates on the host and
  shares with the app (`FLATPAK_ID` and `/.flatpak-info` identify the sandbox).

## Decision

* Inside a Flatpak (`FLATPAK_ID` set), the plug-in serves
  `$XDG_RUNTIME_DIR/app/$FLATPAK_ID/gimp-mcp/bridge.sock`.
* On the host, when the native socket does not exist, the server uses
  `$XDG_RUNTIME_DIR/app/org.gimp.GIMP/gimp-mcp/bridge.sock` if it exists.
  `GIMP_MCP_SOCKET` still wins on both sides.
* `doctor` and `setup` detect Flatpak GIMP with `flatpak info org.gimp.GIMP`
  when no native `gimp-console` is found, and check Python inside the sandbox
  (`flatpak run --command=python3`).
* No `flatpak override` is needed by default. With a custom `GIMP_MCP_SOCKET`,
  `setup` prints the override to run (never applies it).
* CI runs the Flatpak end-to-end test in a privileged, disposable container
  (`ci/Dockerfile.flatpak`, pinned Flathub commit): Flatpak GIMP always uses the
  user's real `~/.config/GIMP`, so the test never runs on a developer account.

## Consequences

* Same commands for native and Flatpak users.
* Flathub may prune old commits: bump `FLATPAK_COMMIT` when the pinned one
  disappears.
* Snap GIMP is not covered (different confinement); untested.
