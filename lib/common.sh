#!/usr/bin/env bash
# Shared input, identity and report operations. Sourced by build-image.sh.

fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
clean_text() { [[ "$1" != *[$'\n\r\t']* ]] || fail 'Values and paths cannot contain tabs or newlines.'; }
validate_url() {
    [[ "$1" =~ ^https?://[A-Za-z0-9.-]+(:[0-9]+)?(/[A-Za-z0-9._~%/+:-]*)?$ ]] || fail 'Repository URLs must be http(s) URLs without credentials, queries or whitespace.'
}
write_lines() {
    local destination=$1; shift
    : > "$destination"
    [[ $# -eq 0 ]] || printf '%s\n' "$@" > "$destination"
}
hash_file() {
    hash_stream < "$1"
}
hash_stream() {
    if command -v sha256sum >/dev/null 2>&1; then sha256sum | cut -d' ' -f1
    else shasum -a 256 | cut -d' ' -f1; fi
}
absolute_path() { case "$1" in /*) printf '%s\n' "$1" ;; *) printf '%s/%s\n' "$PWD" "$1" ;; esac; }
camodel_path() { case "$1" in /*) printf '%s\n' "$1" ;; *) absolute_path "$camodel_dir/$1" ;; esac; }

choose_file() {
    local explicit=$1 directory=$2 pattern=$3 candidate
    local matches=()
    if [[ -n "$explicit" ]]; then absolute_path "$explicit"; return; fi
    if [[ -n "$directory" ]]; then
        for candidate in "$directory"/*; do
            [[ -f "$candidate" ]] || continue
            if [[ "${candidate##*/}" == $pattern ]]; then matches+=("$candidate"); fi
        done
    fi
    if [[ ${#matches[@]} -gt 1 ]]; then fail "Multiple candidates for $pattern in $directory; specify the exact file."; fi
    if [[ ${#matches[@]} -eq 1 ]]; then absolute_path "${matches[0]}"
    elif [[ "$mode" == materials || "$mode" == preview ]]; then printf 'unresolved: %s/%s\n' "${directory:-<set material path>}" "$pattern"
    else fail "Missing $pattern in ${directory:-<unset directory>}; specify its file/root option. Use --materials for guidance."; fi
}

resolve_inputs() {
    local cann_dir= wheel_dir= index name stem
    torch_base=${torch_version%%+*}
    if [[ -n "$cann_root" ]]; then cann_dir="$cann_root/$soc/$cann_version"
    elif [[ -n "$materials_root" ]]; then cann_dir="$materials_root/cann/$cann_version/linux-amd64"; fi
    toolkit=$(choose_file "$toolkit" "$cann_dir" "Ascend-cann-toolkit_${cann_version}_linux-x86_64.run")
    ops=$(choose_file "$ops" "$cann_dir" "Ascend-cann-${soc}-ops_${cann_version}_linux-x86_64.run")
    if [[ "$no_torch" == 0 ]]; then
        if [[ -n "$torch_root" ]]; then wheel_dir="$torch_root/$torch_base"
        elif [[ -n "$materials_root" ]]; then wheel_dir="$materials_root/torch/$torch_base/cp310/linux-amd64"; fi
        torch_wheel=$(choose_file "$torch_wheel" "$wheel_dir" "torch-${torch_version}-cp310-cp310-*_x86_64.whl")
        torch_npu_wheel=$(choose_file "$torch_npu_wheel" "$wheel_dir" "torch_npu-${torch_npu_version}-cp310-cp310-*_x86_64.whl")
    fi
    archive_names=()
    if [[ "$target" == simulation ]]; then
        camodel_dir=$(absolute_path "$camodel_dir")
        camodel_init=$(camodel_path "${camodel_init:-init.sh}")
        if [[ -n "$camodel_env" ]]; then camodel_env=$(camodel_path "$camodel_env")
        elif [[ -f "$camodel_dir/env.sh" ]]; then camodel_env="$camodel_dir/env.sh"; fi
        [[ -z "$camodel_check" ]] || camodel_check=$(camodel_path "$camodel_check")
        for ((index=0; index<${#archives[@]}; index++)); do
            archives[$index]=$(camodel_path "${archives[$index]}")
            name=${archives[$index]##*/}; stem=${name%.zip}
            [[ "$name" == *.zip && "$stem" =~ ^[A-Za-z0-9][A-Za-z0-9._\ -]*$ ]] || fail "Invalid CAModel ZIP name: $name"
            case "$stem" in init.sh|env.sh|check.sh) fail "Reserved CAModel directory name: $stem" ;; esac
            for name in ${archive_names[@]+"${archive_names[@]}"}; do
                [[ "$name" != "${archives[$index]##*/}" ]] || fail "Duplicate CAModel extraction directory: $stem"
            done
            archive_names+=("${archives[$index]##*/}")
        done
    fi
    [[ -z "$constraints" ]] || constraints=$(absolute_path "$constraints")
    [[ -z "$post_install" ]] || post_install=$(absolute_path "$post_install")
}

add_input() {
    local file=$1 name=$2
    clean_text "$file"
    [[ -f "$file" && -r "$file" && -s "$file" ]] || fail "Missing, unreadable or empty input: $file"
    input_files+=("$file"); input_names+=("$name"); input_hashes+=("$(hash_file "$file")")
}

check_inputs() {
    local name file entry
    input_files=(); input_names=(); input_hashes=()
    name=$(printf '%s' "${toolkit##*/}" | tr '[:upper:]' '[:lower:]')
    [[ "$name" == "ascend-cann-toolkit_${cann_version}_linux-x86_64.run" ]] || fail "Toolkit filename/version/architecture mismatch: $toolkit"
    name=$(printf '%s' "${ops##*/}" | tr '[:upper:]' '[:lower:]')
    [[ "$name" == "ascend-cann-${soc}-ops_${cann_version}_linux-x86_64.run" ]] || fail "Ops filename/model/version/architecture mismatch: $ops"
    add_input "$toolkit" packages/cann/toolkit.run
    add_input "$ops" packages/cann/ops.run
    if [[ "$no_torch" == 0 ]]; then
        [[ "$torch_wheel" != "$torch_npu_wheel" ]] || fail 'Torch and torch-npu must be distinct wheel files.'
        for file in "$torch_wheel" "$torch_npu_wheel"; do
            name=${file##*/}
            if [[ "$file" == "$torch_wheel" ]]; then entry="torch-${torch_version}-cp310-cp310-"
            else entry="torch_npu-${torch_npu_version}-cp310-cp310-"; fi
            [[ "$name" == "$entry"manylinux*_x86_64.whl || "$name" == "$entry"linux_x86_64.whl ]] || fail "Wheel filename/version/ABI/architecture mismatch: $file"
            add_input "$file" "packages/torch/$name"
        done
    fi
    if [[ "$target" == simulation ]]; then
        command -v unzip >/dev/null 2>&1 || fail 'unzip is required to check simulation ZIPs.'
        for file in "${archives[@]}"; do
            add_input "$file" "camodel/archives/${file##*/}"
            unzip -tq "$file" >/dev/null || fail "Invalid ZIP: $file"
            while IFS= read -r entry; do
                case "/$entry/" in *'/../'*|*'\'*) fail "Unsafe ZIP entry in $file: $entry" ;; esac
                [[ "$entry" != /* && ! "$entry" =~ ^[A-Za-z]: ]] || fail "Absolute ZIP entry in $file: $entry"
            done < <(unzip -Z1 "$file")
        done
        add_input "$camodel_init" camodel/init.sh
        [[ -z "$camodel_env" ]] || add_input "$camodel_env" camodel/env.sh
        [[ -z "$camodel_check" ]] || add_input "$camodel_check" camodel/check.sh
    fi
    [[ -z "$constraints" ]] || add_input "$constraints" config/constraints.txt
    [[ -z "$post_install" ]] || add_input "$post_install" config/post-install.sh
    add_input "$script_dir/Dockerfile" Dockerfile
    for file in "$script_dir"/scripts/*; do add_input "$file" "scripts/${file##*/}"; done
}

check_docker() {
    command -v docker >/dev/null 2>&1 || fail 'Docker is unavailable; use --check --files-only on a preparation machine.'
    [[ -z "${DOCKER_HOST:-}" ]] || fail 'Use a local Docker context instead of DOCKER_HOST (builder/image-store consistency).'
    docker_context=$(docker context show)
    local endpoint driver platform
    endpoint=$(docker context inspect "$docker_context" --format '{{.Endpoints.docker.Host}}')
    [[ "$endpoint" == unix://* ]] || fail 'Only a local Docker Engine context (unix socket) is supported.'
    docker --context "$docker_context" info >/dev/null || fail 'Docker daemon is unavailable.'
    driver=$(docker --context "$docker_context" buildx inspect "$docker_context" | awk '$1 == "Driver:" { print $2 }')
    [[ "$driver" == docker ]] || fail 'The context builder must use the docker driver; install/enable Docker Buildx with its default Engine builder.'
    platform=$(docker --context "$docker_context" image inspect --format '{{.Os}}/{{.Architecture}}' "$base_image") || fail "Base image is not local: $base_image (prepare it manually)."
    [[ "$platform" == linux/amd64 ]] || fail "Base image is $platform; linux/amd64 is required."
    base_id=$(docker --context "$docker_context" image inspect --format '{{.Id}}' "$base_image")
}

write_parameters() {
    printf 'target=%s\nsoc=%s\ncann=%s\ntorch=%s\ntorch_npu=%s\nno_torch=%s\nbase_id=%s\napt_mirror=%s\npip_index=%s\nworkdir=%s\n' \
        "$target" "$soc" "$cann_version" "$torch_version" "$torch_npu_version" "$no_torch" "$base_id" "$apt_mirror" "$pip_index" "$workdir"
    local item
    for item in ${apt_packages[@]+"${apt_packages[@]}"}; do printf 'apt=%s\n' "$item"; done
    for item in ${pip_packages[@]+"${pip_packages[@]}"}; do printf 'pip=%s\n' "$item"; done
    for item in ${archive_names[@]+"${archive_names[@]}"}; do printf 'archive=%s\n' "$item"; done
}
write_hashes() {
    local index
    for ((index=0; index<${#input_names[@]}; index++)); do printf '%s  %s\n' "${input_hashes[$index]}" "${input_names[$index]}"; done
}
make_identity() {
    local framework prefix repository
    fingerprint=$({ write_parameters; write_hashes; } | hash_stream)
    torch_stage=torch-install
    framework="torch${torch_version//+/_}-npu${torch_npu_version//+/_}"
    if [[ "$no_torch" == 1 ]]; then framework=cann-only; torch_stage=cann-only; fi
    repository=ascend-dev; prefix=npu
    if [[ "$target" == simulation ]]; then repository=ascend-sim; prefix=sim; fi
    image="$repository:$prefix-cann$cann_version-$soc-$framework-py310-amd64-${fingerprint:0:12}"
    [[ ${#image} -le $((${#repository}+129)) ]] || fail 'Generated tag exceeds Docker limit; component version names are too long.'
}
write_manifest() {
    write_parameters
    printf 'base_reference=%s\ncompatibility=%s\nimage=%s\nfingerprint=%s\n' "$base_image" "$compatibility" "$image" "$fingerprint"
    printf 'device_validation=not-performed\nsimulation_validation='
    if [[ "$target" == simulation && -n "$camodel_check" ]]; then
        if [[ "$phase" == complete ]]; then printf 'passed-build-script\n'; else printf 'build-script-required\n'; fi
    else printf 'not-performed\n'; fi
}
show_plan() {
    printf 'Target: %s | SoC: %s | CANN: %s | compatibility: %s\n' "$target" "$soc" "$cann_version" "$compatibility"
    printf 'Base: %s (linux/amd64, Ubuntu 22.04, Python 3.10)\nToolkit: %s\nOps: %s\n' "$base_image" "$toolkit" "$ops"
    if [[ "$no_torch" == 0 ]]; then printf 'Torch: %s\ntorch-npu: %s\n' "$torch_wheel" "$torch_npu_wheel"; fi
    if [[ "$target" == simulation ]]; then
        printf 'CAModel archives: %s\n' "${archives[@]}"
        printf 'CAModel init: %s\nCAModel env: %s\nCAModel check: %s\n' "$camodel_init" "${camodel_env:-none}" "${camodel_check:-none (simulation unverified)}"
    fi
    printf 'Workdir: %s | APT mirror: %s | pip index: %s\n' "$workdir" "${apt_mirror:-base default}" "$pip_index"
    printf 'Network: %s | progress: %s | no-cache: %s | output: %s\n' "$network" "$progress" "$no_cache" "$output_dir"
    if [[ ${#apt_packages[@]} -gt 0 ]]; then printf 'Extra APT: %s\n' "${apt_packages[@]}"; fi
    if [[ ${#pip_packages[@]} -gt 0 ]]; then printf 'Extra pip: %s\n' "${pip_packages[@]}"; fi
    printf 'Constraints: %s | post-install: %s\n' "${constraints:-none}" "${post_install:-none}"
}
materials_help() {
    show_plan
    printf '\nPrepare files manually; the tool does not download or upload them.\n'
    printf 'Base image: docker pull --platform linux/amd64 %q (or docker load a prepared archive)\n' "$base_image"
    printf '%s\n' \
        'CANN Toolkit/ops: https://www.hiascend.com/developer/download/community/result?module=cann' \
        'PyTorch CPU wheel index: https://download.pytorch.org/whl/cpu/torch/' \
        'torch-npu releases: https://gitcode.com/Ascend/pytorch/releases' \
        'Version matching: https://github.com/Ascend/pytorch/blob/master/COMPATIBILITY.md' \
        'CAModel: obtain the specified archives/init/env/check scripts from your provider.' \
        'Storage layouts and compatibility evidence: docs/downloads.md'
}
finish() {
    local status=$?
    trap - EXIT
    if [[ -n "$report_container" ]]; then docker --context "$docker_context" rm "$report_container" >/dev/null 2>&1 || true; fi
    if [[ -n "$run_dir" ]]; then
        printf 'exit_code=%s\nphase=%s\nimage=%s\nimage_id=%s\n' "$status" "$phase" "$image" "$image_id" > "$run_dir/result.txt"
    fi
    [[ -z "$context_dir" ]] || rm -rf -- "$context_dir"
    exit "$status"
}
