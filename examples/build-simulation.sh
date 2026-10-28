#!/usr/bin/env bash
set -euo pipefail
example_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
materials_root=${ASCEND_DEV_MATERIALS_ROOT:-/data/ascend-materials}
# Replace these example archive names with the provider's actual filenames.
bash "$example_dir/../build-image.sh" \
    --target simulation --soc 950 --cann-version 9.1.0 \
    --torch-version 2.10.0+cpu --torch-npu-version 2.10.0.post4 \
    --materials-root "$materials_root" \
    --camodel-dir "${ASCEND_DEV_CAMODEL_DIR:-$materials_root/camodel/950/9.1.0}" \
    --camodel-archive model.zip --camodel-archive tools.zip \
    "$@"
