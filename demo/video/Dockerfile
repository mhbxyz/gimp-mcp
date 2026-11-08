# Virtual desktop for recording the README demo: Xvfb, a real GIMP 3.2 with its
# GUI, a terminal for the AI client, and ffmpeg. Nothing from the host profile.
FROM archlinux:base

ARG ARCH_SNAPSHOT=2026/10/15
RUN echo "Server = https://archive.archlinux.org/repos/${ARCH_SNAPSHOT}/\$repo/os/\$arch" > /etc/pacman.d/mirrorlist \
 && pacman -Syyuu --noconfirm \
 && pacman -S --noconfirm --needed gimp python python-gobject uv git \
      xorg-server-xvfb xdotool alacritty mesa ffmpeg \
      ttf-dejavu ttf-jetbrains-mono noto-fonts noto-fonts-emoji \
 && pacman -Scc --noconfirm

RUN useradd -m -u 1000 demo
USER demo
ENV XDG_RUNTIME_DIR=/tmp/runtime-demo HOME=/home/demo
WORKDIR /home/demo
