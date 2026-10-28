#!/usr/bin/env bash
set -euo pipefail
export LC_ALL=C

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "$script_dir/lib/common.sh"

usage() {
    cat <<'HELP'
Usage: bash build-image.sh --soc MODEL --cann-version VERSION [options]

Environment (Ubuntu 22.04 / amd64 / Python 3.10):
  --target npu|simulation       Output target (default: npu)
  --soc MODEL                  Target model, e.g. 950
  --cann-version VERSION       Exact Toolkit and ops version
  --torch-version VERSION      Exact version, e.g. 2.10.0+cpu
  --torch-npu-version VERSION  Exact package version, e.g. 2.10.0.post4
  --no-torch                   CANN-only image; omit all Torch options
  --base-image IMAGE           Local Ubuntu image (default: ubuntu:22.04)
  --allow-unverified           Allow an undocumented version combination

Local materials (explicit files override directory lookup):
  --materials-root DIR         Unified materials layout (see README.md)
  --cann-root DIR              Legacy layout: DIR/MODEL/CANN_VERSION
  --torch-root DIR             Legacy layout: DIR/TORCH_BASE_VERSION
  --toolkit FILE               Toolkit .run
  --ops FILE                   Model-specific ops .run
  --torch-wheel FILE           PyTorch wheel (cp310 / x86_64)
  --torch-npu-wheel FILE       torch-npu wheel (cp310 / x86_64)

Simulation only:
  --camodel-dir DIR            Simulation input directory
  --camodel-archive FILE       ZIP relative to DIR, repeat for multiple ZIPs
  --camodel-init FILE          Build-time script (default: DIR/init.sh)
  --camodel-env FILE           Runtime environment (default: optional DIR/env.sh)
  --camodel-check FILE         Optional build-time simulation smoke test

Build adjustments:
  --apt-mirror URL             Ubuntu repository base URL
  --pip-index URL              Default: https://pypi.org/simple
  --apt-package PACKAGE        Additional system package; repeatable
  --pip-package SPEC           Additional Python requirement; repeatable
  --pip-constraints FILE       Additional pip constraints
  --post-install FILE          Bash hook executed inside the image
  --workdir DIR                Container working directory (default: /workspace)
  --network default|none       RUN network; none is not a complete offline mode
  --no-cache                   Disable step cache without deleting caches
  --progress plain|auto|tty    Default: plain
  --output-dir DIR             Report parent directory (default: ./build)

Modes (mutually exclusive; default is build):
  --materials                 Download/storage guidance; no Docker needed
  --dry-run                   Preview without writing files or using Docker
  --check                     Validate inputs and local Docker builder
  --files-only                With --check: do not access Docker
  -h, --help                  Show this help

Image names are generated automatically. --tag is not supported.
Core packages and base images must be supplied locally; no downloader is included.
HELP
}

target=${ASCEND_DEV_TARGET:-npu}; soc=${ASCEND_DEV_SOC:-}
cann_version=${ASCEND_DEV_CANN_VERSION:-}; torch_version=${ASCEND_DEV_TORCH_VERSION:-}
torch_npu_version=${ASCEND_DEV_TORCH_NPU_VERSION:-}
base_image=${ASCEND_DEV_BASE_IMAGE:-ubuntu:22.04}
materials_root=${ASCEND_DEV_MATERIALS_ROOT:-}; camodel_dir=${ASCEND_DEV_CAMODEL_DIR:-}
cann_root=; torch_root=; toolkit=; ops=; torch_wheel=; torch_npu_wheel=
camodel_init=; camodel_env=; camodel_check=; constraints=; post_install=
apt_mirror=; pip_index=https://pypi.org/simple; workdir=/workspace
mode=build; files_only=0; no_torch=0; allow_unverified=0; no_cache=0
progress=plain; network=default; output_dir="$PWD/build"
archives=(); apt_packages=(); pip_packages=()
context_dir=; run_dir=; report_container=; image=; image_id=; phase=arguments
trap finish EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

set_mode() {
    [[ "$mode" == build || "$mode" == "$1" ]] || fail 'Choose only one of --materials, --dry-run and --check.'
    mode=$1
}

parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            -h|--help) usage; exit 0 ;;
            --materials) set_mode materials; shift; continue ;;
            --dry-run) set_mode preview; shift; continue ;;
            --check) set_mode check; shift; continue ;;
            --files-only) files_only=1; shift; continue ;;
            --no-torch) no_torch=1; shift; continue ;;
            --allow-unverified) allow_unverified=1; shift; continue ;;
            --no-cache) no_cache=1; shift; continue ;;
            --target|--soc|--cann-version|--torch-version|--torch-npu-version|--base-image|\
            --materials-root|--cann-root|--torch-root|--toolkit|--ops|--torch-wheel|--torch-npu-wheel|\
            --camodel-dir|--camodel-archive|--camodel-init|--camodel-env|--camodel-check|\
            --apt-mirror|--pip-index|--apt-package|--pip-package|--pip-constraints|--post-install|\
            --workdir|--network|--progress|--output-dir)
                [[ $# -ge 2 && -n "$2" && "$2" != --* ]] || fail "$1 requires a value." ;;
            *) fail "Unknown argument: $1. See --help (output tags cannot be customized)." ;;
        esac
        clean_text "$2"
        case "$1" in
            --target) target=$2 ;; --soc) soc=$2 ;; --cann-version) cann_version=$2 ;;
            --torch-version) torch_version=$2 ;; --torch-npu-version) torch_npu_version=$2 ;;
            --base-image) base_image=$2 ;; --materials-root) materials_root=$2 ;;
            --cann-root) cann_root=$2 ;; --torch-root) torch_root=$2 ;;
            --toolkit) toolkit=$2 ;; --ops) ops=$2 ;;
            --torch-wheel) torch_wheel=$2 ;; --torch-npu-wheel) torch_npu_wheel=$2 ;;
            --camodel-dir) camodel_dir=$2 ;; --camodel-archive) archives+=("$2") ;;
            --camodel-init) camodel_init=$2 ;; --camodel-env) camodel_env=$2 ;;
            --camodel-check) camodel_check=$2 ;; --apt-mirror) apt_mirror=$2 ;;
            --pip-index) pip_index=$2 ;; --apt-package) apt_packages+=("$2") ;;
            --pip-package) pip_packages+=("$2") ;; --pip-constraints) constraints=$2 ;;
            --post-install) post_install=$2 ;; --workdir) workdir=$2 ;;
            --network) network=$2 ;; --progress) progress=$2 ;; --output-dir) output_dir=$2 ;;
        esac
        shift 2
    done
}

validate_args() {
    local value version_pattern='^[0-9]+\.[0-9]+\.[0-9]+([a-zA-Z0-9.+_-]*)$'
    for value in "$target" "$soc" "$cann_version" "$torch_version" "$torch_npu_version" \
        "$base_image" "$materials_root" "$camodel_dir"; do clean_text "$value"; done
    [[ "$target" == npu || "$target" == simulation ]] || fail '--target must be npu or simulation.'
    [[ "$soc" =~ ^[A-Za-z0-9]+$ ]] || fail '--soc must be a model such as 950 or 910b.'
    soc=$(printf '%s' "$soc" | tr '[:upper:]' '[:lower:]')
    [[ "$cann_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+[A-Za-z0-9._-]*$ ]] || fail '--cann-version requires an exact version, e.g. 9.1.0.'
    if [[ "$no_torch" == 1 ]]; then
        [[ -z "$torch_version$torch_npu_version$torch_wheel$torch_npu_wheel$torch_root" ]] || fail '--no-torch conflicts with Torch options/environment variables.'
    else
        [[ "$torch_version" =~ $version_pattern && "$torch_npu_version" =~ $version_pattern ]] || fail 'Provide exact --torch-version and --torch-npu-version (or --no-torch).'
    fi
    [[ "$files_only" == 0 || "$mode" == check ]] || fail '--files-only requires --check.'
    [[ "$network" == default || "$network" == none ]] || fail '--network must be default or none.'
    [[ "$progress" == plain || "$progress" == auto || "$progress" == tty ]] || fail '--progress must be plain, auto or tty.'
    [[ "$base_image" != -* && "$base_image" != *[[:space:]]* ]] || fail '--base-image must be an image reference.'
    [[ "$workdir" == /* && "$workdir" != /root && "$workdir" != /root/* ]] || fail '--workdir must be absolute and accessible to non-root users (not /root).'
    validate_url "$pip_index"
    [[ -z "$apt_mirror" ]] || validate_url "$apt_mirror"
    for value in ${apt_packages[@]+"${apt_packages[@]}"}; do
        [[ "$value" =~ ^[a-z0-9][a-z0-9+.-]*(:[a-z0-9]+)?(=[A-Za-z0-9.+:~_-]+)?$ ]] || fail "Invalid APT package: $value"
    done
    local pip_pattern='^[A-Za-z0-9][A-Za-z0-9_.-]*(\[[A-Za-z0-9_,.-]+\])?([<>=!~][A-Za-z0-9_.+*,<>=!~-]+)?$'
    for value in ${pip_packages[@]+"${pip_packages[@]}"}; do
        [[ "$value" =~ $pip_pattern ]] || fail "Invalid pip requirement: $value (use name[extras] and version constraints)."
    done
    if [[ "$target" == simulation ]]; then
        [[ -n "$camodel_dir" && ${#archives[@]} -gt 0 ]] || fail 'Simulation requires --camodel-dir and at least one --camodel-archive.'
    else
        [[ -z "$camodel_dir$camodel_init$camodel_env$camodel_check" && ${#archives[@]} -eq 0 ]] || fail 'CAModel options/environment variables require --target simulation.'
    fi
    compatibility=documented
    if [[ "$cann_version" != 9.1.0 || ( "$no_torch" == 0 && \
        ( "$torch_version" != 2.10.0+cpu || "$torch_npu_version" != 2.10.0.post4 ) ) ]]; then
        compatibility=unverified
        [[ "$allow_unverified" == 1 || "$mode" == materials || "$mode" == preview ]] || fail 'Version combination is unrecorded; see docs/downloads.md or explicitly use --allow-unverified.'
    fi
    # Same framework base version is necessary even for an unverified combination.
    if [[ "$no_torch" == 0 ]]; then
        local torch_base npu_base
        torch_base=$(printf '%s' "$torch_version" | cut -d+ -f1 | sed -E 's/(\.post|\.dev|rc)[0-9].*$//')
        npu_base=$(printf '%s' "$torch_npu_version" | cut -d+ -f1 | sed -E 's/(\.post|\.dev|rc)[0-9].*$//')
        [[ "$torch_base" == "$npu_base" ]] || fail 'Torch and torch-npu base versions differ; --allow-unverified cannot bypass this conflict.'
    fi
}

prepare_context() {
    context_dir=$(mktemp -d "${TMPDIR:-/tmp}/ascend-dev.XXXXXX")
    mkdir -p "$context_dir/packages" "$context_dir/config" "$context_dir/camodel/archives"
    local index
    for ((index=0; index<${#input_files[@]}; index++)); do
        mkdir -p "$(dirname -- "$context_dir/${input_names[$index]}")"
        cp -L "${input_files[$index]}" "$context_dir/${input_names[$index]}"
        [[ "$(hash_file "$context_dir/${input_names[$index]}")" == "${input_hashes[$index]}" ]] || fail "Input changed during staging: ${input_files[$index]}"
    done
    write_lines "$context_dir/config/apt-packages.txt" ${apt_packages[@]+"${apt_packages[@]}"}
    write_lines "$context_dir/config/pip-packages.txt" ${pip_packages[@]+"${pip_packages[@]}"}
    write_lines "$context_dir/camodel/archives.txt" ${archive_names[@]+"${archive_names[@]}"}
    touch "$context_dir/config/constraints.txt"
}

build_command() {
    command_args=(docker --context "$docker_context" buildx build --builder "$docker_context" --load
        --pull=false --platform linux/amd64 --progress "$progress" --network "$network"
        --target "$target" --tag "$image" --iidfile "$run_dir/image-id.txt"
        --build-arg "BASE_IMAGE=$base_image" --build-arg "TORCH_STAGE=$torch_stage"
        --build-arg "TORCH_VERSION=$torch_version" --build-arg "TORCH_NPU_VERSION=$torch_npu_version"
        --build-arg "TORCH_WHEEL_FILE=${torch_wheel##*/}" --build-arg "TORCH_NPU_WHEEL_FILE=${torch_npu_wheel##*/}"
        --build-arg "APT_MIRROR=$apt_mirror" --build-arg "PIP_INDEX_URL=$pip_index"
        --build-arg "DEV_WORKDIR=$workdir" --build-arg "INPUT_FINGERPRINT=$fingerprint"
        -f "$context_dir/Dockerfile")
    [[ "$no_cache" == 0 ]] || command_args+=(--no-cache)
    command_args+=("$context_dir")
}

main() {
    parse_args "$@"
    validate_args
    if [[ "$mode" == build ]]; then
        mkdir -p "$output_dir"
        run_dir=$(mktemp -d "$output_dir/$(date -u +%Y%m%dT%H%M%SZ)-XXXXXX")
        run_dir=$(cd -- "$run_dir" && pwd)
        printf 'Report: %s\n' "$run_dir"
    fi
    phase=materials
    resolve_inputs
    if [[ "$mode" == materials ]]; then materials_help; return; fi
    if [[ "$mode" == preview ]]; then
        show_plan
        printf 'Image: pending (input hashes and local base image ID are resolved at check/build time)\n'
        printf 'Docker: buildx build --load --pull=false --platform linux/amd64 --target %s --network %s\n' "$target" "$network"
        return
    fi
    check_inputs
    if [[ "$files_only" == 1 ]]; then printf 'PASS: local materials (package execution/ABI checks deferred to Docker).\n'; return; fi
    phase=docker
    check_docker
    make_identity
    show_plan
    printf 'Image: %s\n' "$image"
    if [[ "$mode" == check ]]; then printf 'PASS: materials and local Docker builder; image not built.\n'; return; fi
    phase=staging
    prepare_context
    write_manifest > "$run_dir/manifest.txt"
    write_hashes > "$run_dir/materials.sha256"
    cp "$run_dir/manifest.txt" "$run_dir/materials.sha256" "$context_dir/config/"
    phase=build
    build_command
    local status
    if "${command_args[@]}" 2>&1 | tee "$run_dir/build.log"; then status=0; else status=$?; fi
    [[ "$status" == 0 ]] || fail "Docker build failed (pipeline status $status); see $run_dir/build.log."
    image_id=$(cat "$run_dir/image-id.txt")
    [[ -n "$image_id" ]] || fail 'Docker did not return an image ID.'
    phase=report
    [[ "$(docker --context "$docker_context" image inspect --format '{{.Id}}' "$base_image")" == "$base_id" ]] || fail 'Base image changed during the build; rerun with a stable local base reference.'
    report_container=$(docker --context "$docker_context" create "$image_id")
    docker --context "$docker_context" cp "$report_container:/usr/local/share/ascend/installed-packages.txt" "$run_dir/installed-packages.txt"
    docker --context "$docker_context" rm "$report_container" >/dev/null
    report_container=
    phase=complete
    write_manifest > "$run_dir/manifest.txt"
    printf '%s\n' "$image" > "$run_dir/image-ref.txt"
    printf 'Built: %s\nReport: %s\n' "$image" "$run_dir"
}

main "$@"
