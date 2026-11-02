#!/usr/bin/env bash
set -euo pipefail
source /etc/ascend/environment.sh
mkdir -p "$CAMODEL_HOME"
python3 -I /usr/local/lib/ascend/archives.py /tmp/camodel-inputs "$CAMODEL_HOME"

cd "$CAMODEL_HOME"
for script in init.sh env.sh check.sh; do [[ ! -f "$script" ]] || bash -n "$script"; done
bash ./init.sh
unset _ASCEND_SIM_ENV_LOADED
source /etc/ascend/environment.sh
if [[ -f check.sh ]]; then
    bash ./check.sh
    sed -i 's/^simulation_validation=.*/simulation_validation=passed-build-script/' /usr/local/share/ascend/manifest.txt
else
    printf 'Simulation installed; functional validation NOT performed (no --camodel-check).\n'
fi
# Init/check scripts are allowed to customize files, so verify core versions again.
bash /usr/local/lib/ascend/verify-image.sh
