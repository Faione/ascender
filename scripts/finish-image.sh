#!/usr/bin/env bash
set -euo pipefail
touch /etc/ascend/core-constraints.txt
python3 -m pip install -c /etc/ascend/core-constraints.txt -c /tmp/config/constraints.txt \
    build pyyaml 'numpy<2' -r /tmp/config/pip-packages.txt
cp /usr/local/lib/ascend/shell-env.sh /etc/ascend/environment.sh
install -m 755 /usr/local/lib/ascend/entrypoint.sh /usr/local/bin/ascend-entrypoint
printf '%s\n' 'source /etc/ascend/environment.sh' > /etc/profile.d/ascend.sh
printf '\n%s\n' 'source /etc/ascend/environment.sh' >> /etc/bash.bashrc
if [[ -f /tmp/config/post-install.sh ]]; then
    bash -n /tmp/config/post-install.sh
    source /etc/ascend/environment.sh
    bash /tmp/config/post-install.sh
fi
cp /tmp/config/manifest.txt /tmp/config/materials.sha256 /usr/local/share/ascend/
mkdir -p "$DEV_WORKDIR"
bash /usr/local/lib/ascend/verify-image.sh
