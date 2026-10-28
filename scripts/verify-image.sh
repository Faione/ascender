#!/usr/bin/env bash
set -euo pipefail
source /etc/ascend/environment.sh
atc --help >/dev/null
compiler=$(command -v bisheng || find /usr/local/Ascend -type f -path '*/bin/bisheng' -print -quit)
[[ -n "$compiler" && -x "$compiler" ]] || { printf 'Bisheng compiler is missing.\n' >&2; exit 1; }
"$compiler" --version
# Import torch on CPU, but do not import torch_npu or probe NPU hardware here.
python3 -I - "$TORCH_VERSION" "$TORCH_NPU_VERSION" <<'PY'
import importlib.metadata as metadata
import sys

assert sys.version_info[:2] == (3, 10), sys.version
for package, expected in zip(("torch", "torch-npu"), sys.argv[1:]):
    if expected:
        actual = metadata.version(package)
        assert actual == expected, f"{package}: expected {expected}, installed {actual}"
    else:
        try:
            metadata.version(package)
        except metadata.PackageNotFoundError:
            pass
        else:
            raise AssertionError(f"{package} is installed despite --no-torch")
if sys.argv[1]:
    import torch
    torch.add(torch.tensor([1]), torch.tensor([2]))
PY
python3 -m pip check
# Check the common runtime as an unmapped numeric user, with its own writable
# HOME. No host UID is embedded and no mounted workspace is chowned.
setpriv --reuid=65534 --regid=65534 --clear-groups bash -e -c '
    runtime_home=$(mktemp -d); HOME=$runtime_home; export HOME
    trap '\''rm -rf -- "$runtime_home"'\'' EXIT
    unset _ASCEND_CANN_ENV_LOADED _ASCEND_SIM_ENV_LOADED
    source /etc/ascend/environment.sh
    atc --help >/dev/null
    "$1" --version >/dev/null
    if [[ -n "$2" ]]; then python3 -I -c "import torch; assert torch.tensor([1]).item() == 1"; fi
' bash "$compiler" "$TORCH_VERSION"
{
    printf '[system]\n'
    dpkg-query -W -f='${Package}=${Version}\n'
    printf '\n[python]\n'
    python3 -m pip freeze --all
} > /usr/local/share/ascend/installed-packages.txt
