# Reproducible GIMP environment for end-to-end tests.
# Arch Linux pinned to an Arch Linux Archive snapshot so every package
# (GIMP, GEGL, PyGObject, Python) has a fixed version.
FROM archlinux:base

ARG ARCH_SNAPSHOT=2026/10/15
RUN echo "Server = https://archive.archlinux.org/repos/${ARCH_SNAPSHOT}/\$repo/os/\$arch" > /etc/pacman.d/mirrorlist \
 && pacman -Syyuu --noconfirm \
 && pacman -S --noconfirm --needed gimp python python-gobject uv git ttf-dejavu \
 && pacman -Scc --noconfirm

RUN useradd -m tester
USER tester
ENV XDG_RUNTIME_DIR=/tmp/runtime-tester
WORKDIR /home/tester
