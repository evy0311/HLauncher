# ARM64 Linux image-building tools for Apple Silicon / ARM64 Docker hosts.
FROM debian:bookworm-slim
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    ca-certificates curl xz-utils util-linux parted udev fdisk zerofree cloud-guest-utils e2fsprogs dosfstools \
    openssl git python3 build-essential pkg-config rsync systemd procps \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /work
CMD ["/bin/bash"]
