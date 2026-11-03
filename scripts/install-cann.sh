#!/usr/bin/env bash
set -euo pipefail
python3 -I /usr/local/lib/ascend/python_deps.py snapshot /tmp/cann-python-before.json
for package in toolkit ops; do
    if [[ "${STRICT:-0}" == 1 ]]; then bash "/tmp/cann-packages/$package.run" --check; fi
    bash "/tmp/cann-packages/$package.run" --install --quiet
done
# Keep the complete installation layer, including links and system integration.
# Raw installers are bind-mounted, so they never become image-layer files.
for env_file in /usr/local/Ascend/cann/set_env.sh /usr/local/Ascend/ascend-toolkit/set_env.sh; do
    if [[ -r "$env_file" ]]; then
        printf 'source %q\n' "$env_file" > /etc/ascend/cann-env.sh
        source /usr/local/lib/ascend/shell-env.sh
        python3 /usr/local/lib/ascend/python_deps.py requirements /etc/ascend/cann-requirements.txt \
            --before /tmp/cann-python-before.json
        rm /tmp/cann-python-before.json
        exit 0
    fi
done
printf 'CANN installation did not provide a supported set_env.sh path.\n' >&2
exit 1
