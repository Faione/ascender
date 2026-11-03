#!/usr/bin/env bash
set -euo pipefail
source /etc/os-release
[[ "$ID" == ubuntu && "$VERSION_ID" == 22.04 && "$(dpkg --print-architecture)" == amd64 ]] || {
    printf 'Base image must be Ubuntu 22.04 amd64.\n' >&2; exit 1;
}
# Package installation belongs in the image; the host never installs dependencies.
[[ "$MIRROR_URL" =~ ^https?://[A-Za-z0-9.-]+(:[0-9]+)?/?$ ]] || {
    printf 'MIRROR_URL must be an http(s) origin without a path.\n' >&2; exit 1;
}
mirror="${MIRROR_URL%/}"
sed -Ei "s#https?://([a-z0-9.-]*archive.ubuntu.com|security.ubuntu.com)/ubuntu/?#${mirror}/ubuntu#g" /etc/apt/sources.list
extra_packages=()
while IFS= read -r package; do [[ -z "$package" ]] || extra_packages+=("$package"); done < /tmp/apt-packages.txt
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    python3 python3-pip python3-dev build-essential cmake ninja-build pkg-config git unzip util-linux \
    libssl-dev zlib1g-dev libffi-dev ca-certificates ${extra_packages[@]+"${extra_packages[@]}"}
rm -rf /var/lib/apt/lists/*
python3 -c 'import sys; assert sys.version_info[:2] == (3, 10), sys.version'
python3 -m pip config --global set global.index-url "${mirror}/pypi/simple"
if [[ "$mirror" == http://* ]]; then
    python3 -m pip config --global set global.trusted-host "${mirror#*://}"
fi
chmod 644 /etc/pip.conf
mkdir -p /etc/ascend /usr/local/share/ascend
