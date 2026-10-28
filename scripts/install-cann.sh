#!/usr/bin/env bash
set -euo pipefail
for package in toolkit ops; do
    bash "/tmp/cann-packages/$package.run" --check
    bash "/tmp/cann-packages/$package.run" --install --quiet
done
# Keep the complete installation layer, including links and system integration.
# Raw installers are bind-mounted, so they never become image-layer files.
for env_file in /usr/local/Ascend/cann/set_env.sh /usr/local/Ascend/ascend-toolkit/set_env.sh; do
    if [[ -r "$env_file" ]]; then
        printf 'source %q\n' "$env_file" > /etc/ascend/cann-env.sh
        exit 0
    fi
done
printf 'CANN installation did not provide a supported set_env.sh path.\n' >&2
exit 1
