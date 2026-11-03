#!/usr/bin/env bash
set -Eeuo pipefail
trap 'status=$?; printf "ERROR: %s:%s: %s (exit %s)\n" "${BASH_SOURCE[0]}" "$LINENO" "$BASH_COMMAND" "$status" >&2; exit "$status"' ERR
printf '[finish-image] Configuring shell environment\n'
cp /usr/local/lib/ascend/shell-env.sh /etc/ascend/environment.sh
install -m 755 /usr/local/lib/ascend/entrypoint.sh /usr/local/bin/ascend-entrypoint
printf '%s\n' 'source /etc/ascend/environment.sh' > /etc/profile.d/ascend.sh
printf '\n%s\n' 'source /etc/ascend/environment.sh' >> /etc/bash.bashrc
source /etc/ascend/environment.sh
touch /etc/ascend/core-constraints.txt
if [[ -s /etc/ascend/cann-requirements.txt || -s /tmp/config/pip-packages.txt ]]; then
    printf '[finish-image] Installing declared CANN dependencies and requested Python packages\n'
    python3 -m pip install -c /etc/ascend/core-constraints.txt -c /tmp/config/constraints.txt \
        -r /etc/ascend/cann-requirements.txt -r /tmp/config/pip-packages.txt
fi
if [[ -f /tmp/config/post-install.sh ]]; then
    printf '[finish-image] Running post-install.sh\n'
    bash /tmp/config/post-install.sh
fi
printf '[finish-image] Saving build manifest\n'
cp /tmp/config/manifest.txt /usr/local/share/ascend/
if [[ -f /tmp/config/materials.sha256 ]]; then
    cp /tmp/config/materials.sha256 /usr/local/share/ascend/
fi
mkdir -p "$DEV_WORKDIR"
if [[ "${STRICT:-0}" == 1 ]]; then
    printf '[finish-image] Running verify-image.sh\n'
    bash /usr/local/lib/ascend/verify-image.sh
fi
python3 /usr/local/lib/ascend/python_deps.py inventory /usr/local/share/ascend/installed-packages.txt
