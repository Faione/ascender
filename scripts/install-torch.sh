#!/usr/bin/env bash
set -euo pipefail
printf 'torch==%s\ntorch-npu==%s\nnumpy<2\n' "$TORCH_VERSION" "$TORCH_NPU_VERSION" > /etc/ascend/core-constraints.txt
python3 -m pip install \
    -c /etc/ascend/core-constraints.txt -c /tmp/user-constraints.txt \
    "/tmp/torch-packages/$TORCH_WHEEL_FILE" "/tmp/torch-packages/$TORCH_NPU_WHEEL_FILE"
