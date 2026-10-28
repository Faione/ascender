#!/usr/bin/env bash
set -e
source /etc/ascend/environment.sh
if [[ $# -eq 0 ]]; then set -- /bin/bash; fi
exec "$@"
