# syntax=docker/dockerfile:1

##########################################################################
# Build stage — compile the official Proton Bridge from source (no GUI)  #
##########################################################################
FROM golang:1.26-bookworm AS build

ARG BRIDGE_TAG=v3.25.0

# Build prerequisites for `make build-nogui` (see BUILDS.md).
RUN apt-get update && apt-get install -y --no-install-recommends \
        make gcc pkg-config git sed ca-certificates \
        libsecret-1-dev libglvnd-dev libfido2-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src
# Full clone (not --depth 1): the Makefile derives version/revision from git
# via utils/get_revision.sh, so it needs history and the tag object.
RUN git clone https://github.com/ProtonMail/proton-bridge.git . \
    && git checkout "${BRIDGE_TAG}"

# Bind the local IMAP/SMTP listeners to all interfaces so the sibling
# mcp-server container can reach the bridge over the compose network.
RUN sed -i 's/Host = "127.0.0.1"/Host = "0.0.0.0"/' internal/constants/constants.go \
    && grep -q 'Host = "0.0.0.0"' internal/constants/constants.go

RUN make build-nogui

# The nogui build emits the `bridge` binary at the repo root. Copy it to a
# stable path (find as a safety net in case the tag moves the output).
RUN install -Dm755 "$(find . -maxdepth 2 -type f -name bridge | head -n1)" /out/bridge \
    && /out/bridge --version || true

##########################################################################
# Runtime stage — headless bridge with a pass/gpg keychain               #
##########################################################################
FROM debian:bookworm-slim AS runtime

# gnupg + pass provide the keychain backend the bridge uses on headless
# Linux; libsecret is needed because the CGO binary links against it.
RUN apt-get update && apt-get install -y --no-install-recommends \
        gnupg pass ca-certificates libsecret-1-0 libfido2-1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=build /out/bridge /usr/local/bin/bridge
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

ENV HOME=/root \
    GNUPGHOME=/root/.gnupg
WORKDIR /root

# Default IMAP/SMTP ports for the official bridge.
EXPOSE 1143 1025

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
# Normal operation runs headless. The one-time login overrides this with
# `bridge --cli` via `docker compose run`.
CMD ["bridge", "--noninteractive"]
