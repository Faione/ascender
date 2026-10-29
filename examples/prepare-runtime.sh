#!/usr/bin/env bash
# Generate a complete runtime configuration. This script never starts containers.
set -euo pipefail
export LC_ALL=C
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
usage() {
    cat <<'HELP'
Usage: bash prepare-runtime.sh --image-ref-file FILE --code-dir DIR --output-dir DIR [options]
  --image-ref-file FILE   Build report's image-ref.txt (local image required)
  --code-dir DIR          Existing external source directory
  --output-dir DIR        Write compose.yaml, identity/ and home/ here
  --target npu|simulation Default: read dev.ascend.target from the image
  --uid ID               Default: id -u (non-root)
  --gid ID               Default: id -g
  --user NAME            Default: developer
  --group-add GID        Additional supplementary group; repeatable
  --device FILE          NPU device; repeatable; default: davinci0, davinci_manager, hisi_hdc
  --driver-root DIR      NPU driver source (default: /usr/local/Ascend/driver)
  --dcmi-dir DIR          NPU DCMI source (default: /usr/local/dcmi)
  --install-info FILE    NPU install info source (default: /etc/ascend_install.info)
  -h, --help             Show help

All runtime settings come from CLI/defaults, not ASCEND_IMAGE or LOCAL_* variables.
The generated Compose file requires no exports or --env-file.
HELP
}
clean_path() { [[ "$1" != *[$'\n\r\t']* ]] || fail 'Paths cannot contain tabs or newlines.'; }
absolute_path() { case "$1" in /*) printf '%s\n' "$1" ;; *) printf '%s/%s\n' "$PWD" "$1" ;; esac; }
yaml_string() {
    # YAML quoting and Compose interpolation are separate: $$ keeps a literal $.
    local value=${1//\$/\$\$}
    value=${value//\'/\'\'}
    printf "'%s'" "$value"
}
bind_mount() {
    printf '      - type: bind\n        source: '; yaml_string "$1"
    printf '\n        target: '; yaml_string "$2"
    printf '\n'
    [[ "${3:-rw}" != ro ]] || printf '        read_only: true\n'
    printf '        bind:\n          create_host_path: false\n'
}
add_group() {
    local gid=$1 existing
    [[ "$gid" =~ ^[0-9]{1,10}$ ]] || fail "Invalid group ID: $gid"
    gid=$((10#$gid))
    ((gid <= 2147483647)) || fail "Group ID is out of range: $gid"
    for existing in ${groups[@]+"${groups[@]}"}; do [[ "$existing" != "$gid" ]] || return 0; done
    groups+=("$gid")
}

image_file=; code_dir=; output_dir=; target=
local_uid=$(id -u); local_gid=$(id -g); username=developer
driver_root=/usr/local/Ascend/driver; dcmi_dir=/usr/local/dcmi; install_info=/etc/ascend_install.info
devices=(); groups=(); npu_options=0; temp_dir=
while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help) usage; exit 0 ;;
        --image-ref-file|--code-dir|--output-dir|--target|--uid|--gid|--user|--group-add|\
        --device|--driver-root|--dcmi-dir|--install-info)
            [[ $# -ge 2 && -n "$2" && "$2" != --* ]] || fail "$1 requires a value."
            clean_path "$2" ;;
        *) fail "Unknown argument: $1 (see --help)." ;;
    esac
    case "$1" in
        --image-ref-file) image_file=$2 ;; --code-dir) code_dir=$2 ;; --output-dir) output_dir=$2 ;;
        --target) target=$2 ;; --uid) local_uid=$2 ;; --gid) local_gid=$2 ;; --user) username=$2 ;;
        --group-add) add_group "$2" ;;
        --device) devices+=("$2"); npu_options=1 ;;
        --driver-root) driver_root=$2; npu_options=1 ;;
        --dcmi-dir) dcmi_dir=$2; npu_options=1 ;;
        --install-info) install_info=$2; npu_options=1 ;;
    esac
    shift 2
done
[[ -n "$image_file" && -n "$code_dir" && -n "$output_dir" ]] || fail '--image-ref-file, --code-dir and --output-dir are required.'
[[ -r "$image_file" && -s "$image_file" ]] || fail "Cannot read image reference file: $image_file"
[[ -d "$code_dir" && -r "$code_dir" && -w "$code_dir" ]] || fail "Source directory must exist and be readable/writable: $code_dir"
code_dir=$(cd -- "$code_dir" && pwd -P)
image=$(cat "$image_file")
[[ -n "$image" && "$image" != -* && "$image" != *[[:space:]]* ]] || fail 'image-ref.txt must contain one image reference.'
image_id=$(docker image inspect --format '{{.Id}}' "$image")
image_target=$(docker image inspect --format '{{index .Config.Labels "dev.ascend.target"}}' "$image_id")
if [[ -z "$target" ]]; then target=$image_target; fi
[[ "$target" == npu || "$target" == simulation ]] || fail 'Image has no recognized target label; provide --target npu or simulation.'
if [[ "$image_target" == npu || "$image_target" == simulation ]]; then
    [[ "$target" == "$image_target" ]] || fail '--target conflicts with the image target label.'
fi
if [[ "$target" == npu ]]; then
    [[ ${#devices[@]} -gt 0 ]] || devices=(/dev/davinci0 /dev/davinci_manager /dev/hisi_hdc)
    for device in "${devices[@]}"; do
        [[ "$device" == /* && "$device" != *:* && -c "$device" ]] || fail "NPU device must be an existing absolute character-device path: $device"
        gid=$(stat -c '%g' "$device" 2>/dev/null || stat -f '%g' "$device")
        add_group "$gid"
    done
    for directory in "$driver_root/lib64" "$dcmi_dir"; do
        [[ -d "$directory" && -r "$directory" ]] || fail "Missing/unreadable driver directory: $directory"
    done
    for file in "$driver_root/version.info" "$install_info"; do
        [[ -f "$file" && -r "$file" ]] || fail "Missing/unreadable driver info: $file"
    done
    driver_root=$(cd -- "$driver_root" && pwd -P)
    dcmi_dir=$(cd -- "$dcmi_dir" && pwd -P)
    install_info=$(absolute_path "$install_info")
else
    [[ "$npu_options" == 0 ]] || fail 'Device and driver options require an NPU image.'
fi

mkdir -p "$output_dir"
output_dir=$(cd -- "$output_dir" && pwd -P)
temp_dir=$(mktemp -d "$output_dir/.prepare-runtime.XXXXXX")
cleanup() { local status=$?; trap - EXIT; rm -rf -- "$temp_dir"; exit "$status"; }
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

ASCEND_IMAGE="$image_id" IDENTITY_DIR="$temp_dir/identity" \
    LOCAL_UID="$local_uid" LOCAL_GID="$local_gid" LOCAL_USER="$username" \
    bash "$script_dir/prepare-user.sh"
# Read normalized IDs as data, without sourcing the generated environment file.
local_uid=$(awk -F= '$1 == "uid" { print $2 }' "$temp_dir/identity/identity.txt")
local_gid=$(awk -F= '$1 == "gid" { print $2 }' "$temp_dir/identity/identity.txt")
mkdir -p "$output_dir/home" "$output_dir/identity"
{
    printf '# Generated by prepare-runtime.sh; no environment interpolation is required.\nservices:\n  ascend:\n    image: '
    yaml_string "$image"
    printf '\n    pull_policy: never\n    user: '\''%s:%s'\''\n' "$local_uid" "$local_gid"
    printf '    working_dir: /workspace/code\n    command: ["sleep", "infinity"]\n'
    printf '    environment:\n      HOME: /workspace/home\n      XDG_CACHE_HOME: /workspace/home/.cache\n'
    if [[ ${#groups[@]} -gt 0 ]]; then printf '    group_add:\n'; printf "      - '%s'\n" "${groups[@]}"; fi
    if [[ "$target" == npu ]]; then
        printf '    devices:\n'
        for device in "${devices[@]}"; do printf '      - '; yaml_string "$device:$device"; printf '\n'; done
    fi
    printf '    volumes:\n'
    bind_mount "$code_dir" /workspace/code
    bind_mount "$output_dir/home" /workspace/home
    bind_mount "$output_dir/identity/passwd" /etc/passwd ro
    bind_mount "$output_dir/identity/group" /etc/group ro
    if [[ "$target" == npu ]]; then
        bind_mount "$dcmi_dir" /usr/local/dcmi ro
        bind_mount "$driver_root/lib64" /usr/local/Ascend/driver/lib64 ro
        bind_mount "$driver_root/version.info" /usr/local/Ascend/driver/version.info ro
        bind_mount "$install_info" /etc/ascend_install.info ro
    fi
} > "$temp_dir/compose.yaml"
chmod 644 "$temp_dir/compose.yaml"
mv "$temp_dir/identity/passwd" "$temp_dir/identity/group" "$temp_dir/identity/identity.txt" "$output_dir/identity/"
mv "$temp_dir/compose.yaml" "$output_dir/compose.yaml"
printf 'Prepared %s runtime: %s\n' "$target" "$output_dir/compose.yaml"
printf 'Start: docker compose -f %q up -d\n' "$output_dir/compose.yaml"
