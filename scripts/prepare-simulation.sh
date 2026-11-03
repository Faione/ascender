#!/usr/bin/env bash
set -euo pipefail
source /etc/ascend/environment.sh
mkdir -p "$CAMODEL_HOME"
python3 -I /usr/local/lib/ascend/archives.py /tmp/camodel-inputs "$CAMODEL_HOME"
python3 -I /usr/local/lib/ascend/simulation.py /tmp/camodel-inputs/settings.json "$CAMODEL_HOME"

cd "$CAMODEL_HOME"
unset _ASCEND_SIM_ENV_LOADED
source /etc/ascend/environment.sh
if [[ -f /tmp/camodel-inputs/init.sh ]]; then bash ./init.sh; fi
unset _ASCEND_SIM_ENV_LOADED
source /etc/ascend/environment.sh
if [[ -f /tmp/camodel-inputs/check.sh ]]; then
    bash ./check.sh
    sed -i 's/^simulation_validation=.*/simulation_validation=passed-build-script/' /usr/local/share/ascend/manifest.txt
else
    printf 'Simulation installed; functional validation NOT performed (no --camodel-check).\n'
fi
# Refresh the inventory after optional hooks; verify only in strict mode.
if [[ "${STRICT:-0}" == 1 ]]; then bash /usr/local/lib/ascend/verify-image.sh; fi
python3 /usr/local/lib/ascend/python_deps.py inventory /usr/local/share/ascend/installed-packages.txt
