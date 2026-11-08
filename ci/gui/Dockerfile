# GIMP with its interface for the GUI end-to-end tests (#105): the CI's pinned Arch snapshot with
# Xvfb (a virtual display) and xdotool (keys and windows, like a user).
FROM archlinux:base

ARG ARCH_SNAPSHOT=2026/10/15
RUN echo "Server = https://archive.archlinux.org/repos/${ARCH_SNAPSHOT}/\$repo/os/\$arch" > /etc/pacman.d/mirrorlist \
 && pacman -Syyuu --noconfirm \
 && pacman -S --noconfirm --needed gimp python python-gobject uv git xorg-server-xvfb xdotool \
      mesa ttf-dejavu \
 && pacman -Scc --noconfirm

RUN useradd -m tester
USER tester
ENV XDG_RUNTIME_DIR=/tmp/runtime-tester HOME=/home/tester
WORKDIR /home/tester
