# One image per distribution of ci/distros/distros.json: the distribution's own
# GIMP packages + uv. Base images are pinned by digest; the package versions
# resolved at build time are printed by the smoke test.
ARG BASE_IMAGE
FROM ghcr.io/astral-sh/uv:0.9.26 AS uv
FROM ${BASE_IMAGE}
ARG INSTALL
RUN sh -euxc "${INSTALL}"
COPY --from=uv /uv /uvx /usr/local/bin/
RUN (useradd -m tester 2>/dev/null || adduser -D tester) && mkdir -p /tmp/runtime-tester && chown tester /tmp/runtime-tester && chmod 700 /tmp/runtime-tester
USER tester
WORKDIR /home/tester
ENV XDG_RUNTIME_DIR=/tmp/runtime-tester
