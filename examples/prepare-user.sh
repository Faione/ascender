#!/usr/bin/env bash
# Prepare container-local account files; never edit host /etc or start a container.
set -euo pipefail
export LC_ALL=C

fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
if [[ "${1:-}" == --help ]]; then
    printf '%s\n' 'Usage: ASCEND_IMAGE=... IDENTITY_DIR=/absolute/path bash prepare-user.sh' \
        'Optional: LOCAL_UID / LOCAL_GID (default: id -u / id -g), LOCAL_USER.'
    exit 0
fi
[[ $# -eq 0 ]] || fail 'No positional arguments are accepted; see --help.'
image=${ASCEND_IMAGE:?set ASCEND_IMAGE to the generated image reference}
identity_dir=${IDENTITY_DIR:?set IDENTITY_DIR to an absolute directory}
local_uid=${LOCAL_UID:-$(id -u)}
local_gid=${LOCAL_GID:-$(id -g)}
[[ "$local_uid" =~ ^[0-9]{1,10}$ && "$local_gid" =~ ^[0-9]{1,10}$ ]] || fail 'LOCAL_UID and LOCAL_GID must be numeric IDs.'
local_uid=$((10#$local_uid)); local_gid=$((10#$local_gid))
((local_uid > 0 && local_uid <= 2147483647 && local_gid <= 2147483647)) || fail 'Use a non-root UID and a valid GID (0..2147483647).'
[[ "$identity_dir" == /* && "$identity_dir" != *[$'\r\n\t']* ]] || fail 'IDENTITY_DIR must be an absolute path without control characters.'

temp_dir=; container=
cleanup() {
    local status=$?
    trap - EXIT
    if [[ -n "$container" ]]; then docker rm "$container" >/dev/null 2>&1 || true; fi
    [[ -z "$temp_dir" ]] || rm -rf -- "$temp_dir"
    exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# Inspect first and create by immutable ID, so a missing image is never pulled.
image_id=$(docker image inspect --format '{{.Id}}' "$image")
[[ -n "$image_id" ]] || fail 'The selected image is not available locally.'
mkdir -p "$identity_dir"
temp_dir=$(mktemp -d "$identity_dir/.prepare.XXXXXX")
container=$(docker create "$image_id")
docker cp "$container:/etc/passwd" "$temp_dir/base-passwd"
docker cp "$container:/etc/group" "$temp_dir/base-group"
docker rm "$container" >/dev/null
container=

existing_user=$(awk -F: -v uid="$local_uid" '$3 == uid { print $1; exit }' "$temp_dir/base-passwd")
username=${LOCAL_USER:-${existing_user:-ascend-$local_uid}}
[[ "$username" =~ ^[A-Za-z_][A-Za-z0-9_.-]{0,31}$ && "$username" != root ]] || fail 'LOCAL_USER must be a non-root Unix username (up to 32 characters).'
conflict=$(awk -F: -v name="$username" -v uid="$local_uid" '$1 == name && $3 != uid { print $1; exit }' "$temp_dir/base-passwd")
[[ -z "$conflict" ]] || fail "Username $username already belongs to another UID; choose another LOCAL_USER."

# Retain image system accounts. Replace only the selected UID's record, including
# its home, so pwd.getpwuid() and HOME agree in ordinary docker exec processes.
awk -F: -v uid="$local_uid" '$3 != uid' "$temp_dir/base-passwd" > "$temp_dir/passwd"
printf '%s:*:%s:%s:Ascend developer:/workspace/home:/bin/bash\n' "$username" "$local_uid" "$local_gid" >> "$temp_dir/passwd"
cp "$temp_dir/base-group" "$temp_dir/group"
group_name=$(awk -F: -v gid="$local_gid" '$3 == gid { print $1; exit }' "$temp_dir/base-group")
if [[ -z "$group_name" ]]; then
    group_name=ascend-$local_gid
    conflict=$(awk -F: -v name="$group_name" '$1 == name { print $1; exit }' "$temp_dir/base-group")
    [[ -z "$conflict" ]] || fail "Group name $group_name already belongs to another GID."
    printf '%s:*:%s:%s\n' "$group_name" "$local_gid" "$username" >> "$temp_dir/group"
fi
printf 'image_id=%s\nuid=%s\ngid=%s\nuser=%s\n' "$image_id" "$local_uid" "$local_gid" "$username" > "$temp_dir/identity.txt"
chmod 644 "$temp_dir/passwd" "$temp_dir/group" "$temp_dir/identity.txt"
# Publish only after both databases are ready. Recreate running containers after
# regenerating these files, since existing file bind mounts retain their inode.
mv "$temp_dir/passwd" "$temp_dir/group" "$temp_dir/identity.txt" "$identity_dir/"
printf 'Prepared %s (%s:%s), group %s\nIdentity files: %s\n' "$username" "$local_uid" "$local_gid" "$group_name" "$identity_dir"
