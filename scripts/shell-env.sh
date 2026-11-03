#!/usr/bin/env bash
# Shared by the entrypoint, interactive Bash and login Bash. No root operations.
[[ -n "${BASH_VERSION:-}" ]] || return 0
_ascend_source_env() {
    # Vendor scripts may read unset search-path variables. Restore the caller's
    # nounset setting instead of forcing every interactive shell into one mode.
    local nounset=0 status
    case $- in *u*) nounset=1; set +u ;; esac
    if source "$1"; then status=0; else status=$?; fi
    [[ "$nounset" == 0 ]] || set -u
    return "$status"
}
if [[ "${_ASCEND_CANN_ENV_LOADED:-}" != 1 ]]; then
    _ascend_source_env /etc/ascend/cann-env.sh || return $?
    export _ASCEND_CANN_ENV_LOADED=1
fi
if [[ "${ASCEND_ENV_MODE:-npu}" == simulation && "${_ASCEND_SIM_ENV_LOADED:-}" != 1 ]]; then
    if [[ -f "${CAMODEL_HOME:?}/env.sh" ]]; then _ascend_source_env "$CAMODEL_HOME/env.sh" || return $?; fi
    # Apply built-in settings last, keeping the CAModel library directory first.
    if [[ -f /etc/ascend/camodel-env.sh ]]; then _ascend_source_env /etc/ascend/camodel-env.sh || return $?; fi
    export _ASCEND_SIM_ENV_LOADED=1
fi
