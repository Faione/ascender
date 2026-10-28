#!/usr/bin/env bash
set -euo pipefail
example_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
bash "$example_dir/../build-image.sh" \
    --target npu --soc 950 --cann-version 9.1.0 \
    --torch-version 2.10.0+cpu --torch-npu-version 2.10.0.post4 \
    --materials-root "${ASCEND_DEV_MATERIALS_ROOT:-/data/ascend-materials}" \
    "$@"
