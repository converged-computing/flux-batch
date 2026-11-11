#!/bin/bash
#
# launch-common.sh - shared setup for the flux-batch usernetes launchers.
#
# This file is meant to be sourced by launch-control-plane.sh and
# launch-worker.sh, not executed directly. The launchers are thin wrappers:
# all of the real node setup (podman storage, image builds, kubeadm) lives in
# the usernetes checkout itself, under <USERNETES_ROOT>/service/. The
# launchers only orchestrate: who starts first, how workers find the join
# command, when the batch job is allowed to proceed, and how nodes leave.
#
# Knobs (all overridable from the environment; the flux-batch module renders
# them into the modprobe task from the jobspec attributes):
#
#   USERNETES_ROOT             Usernetes checkout (hetchy branch) whose
#                              service/ scripts do the per-node work and which
#                              is copied to each node as the template.
#                              Default: /usr/workspace/usernetes/usernetes-wip
#   USERNETES_CLUSTER_NAME     Name of this cluster. A burst job joins an
#                              existing cluster by using the same name.
#                              Default: default
#   USERNETES_SHARED_ROOT      Shared-filesystem directory under which each
#                              cluster gets a state directory.
#                              Default: $HOME/.usernetes/clusters
#   USERNETES_SHARED_DIR       The cluster state directory itself. Derived as
#                              <shared root>/<cluster name> unless set.
#   USERNETES_EXPECTED_NODES   Nodes the control plane waits for before
#                              installing the CNI (control plane included).
#                              Default: 1
#   USERNETES_WAIT_TIMEOUT     Seconds to wait for any one phase (join command,
#                              node registration, Ready). Image builds are slow
#                              with vfs storage. Default: 3600
#   USERNETES_RECONCILE_INTERVAL
#                              Seconds between reconcile passes on the control
#                              plane (burst arrivals, departures). Default: 30
#   USERNETES_LOG_DIR          Where launcher and service logs are written on
#                              each node. Default: /tmp/$USER
#   USERNETES_NODE_LOCK        Host-local lock allowing one usernetes launcher
#                              per host. Default: /tmp/$USER/.flux-batch-usernetes.lock
#   USERNETES_POLL_INTERVAL    Seconds between polls while waiting on a phase
#                              (mostly for tests). Default: 5
#
# Everything else (USERNETES_CONTAINER_TECH, USERNETES_STORAGE_ROOT,
# USERNETES_CNI, ...) is passed through untouched to the usernetes service
# scripts, which document their own knobs in service/usernetes-common.sh.

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    echo "launch-common.sh should be sourced, not executed directly." >&2
    exit 1
fi

set -euo pipefail

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - INFO - $1"
}

error_exit() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - ERROR - $1" >&2
    exit 1
}

# Ensure HOME is usable: the launchers may run under a Flux broker where the
# environment is thinner than a login shell.
u7s_setup_home() {
    USERNAME=$(whoami)
    export USERNAME
    if [[ -z "${HOME:-}" || ! -d "${HOME}" ]]; then
        local user_home_dir
        user_home_dir=$(getent passwd "${USERNAME}" | cut -d: -f6)
        if [[ -z "${user_home_dir}" || ! -d "${user_home_dir}" ]]; then
            error_exit "Cannot determine home directory for ${USERNAME}."
        fi
        export HOME="${user_home_dir}"
    fi
}

u7s_setup_env() {
    u7s_setup_home

    export USERNETES_ROOT="${USERNETES_ROOT:-/usr/workspace/usernetes/usernetes-wip}"
    export USERNETES_CLUSTER_NAME="${USERNETES_CLUSTER_NAME:-default}"
    export USERNETES_SHARED_ROOT="${USERNETES_SHARED_ROOT:-${HOME}/.usernetes/clusters}"
    export USERNETES_SHARED_DIR="${USERNETES_SHARED_DIR:-${USERNETES_SHARED_ROOT}/${USERNETES_CLUSTER_NAME}}"
    export USERNETES_EXPECTED_NODES="${USERNETES_EXPECTED_NODES:-1}"
    export USERNETES_WAIT_TIMEOUT="${USERNETES_WAIT_TIMEOUT:-3600}"
    export USERNETES_RECONCILE_INTERVAL="${USERNETES_RECONCILE_INTERVAL:-30}"
    export USERNETES_LOG_DIR="${USERNETES_LOG_DIR:-/tmp/${USERNAME}}"
    mkdir -p "${USERNETES_LOG_DIR}"

    # The usernetes service scripts copy USERNETES_TEMPLATE_PATH to the node
    # and leave the join command in USERNETES_SHARED_DIR. Point both at us.
    export USERNETES_TEMPLATE_PATH="${USERNETES_TEMPLATE_PATH:-${USERNETES_ROOT}}"

    # Where the usernetes service scripts put the working copy on each node.
    export TMPDIR="${TMPDIR:-/tmp/${USERNAME}}"

    # The node name usernetes registers for this host (NODE_NAME in the
    # usernetes Makefile). Overridable, like NODE_NAME itself.
    U7S_NODE_NAME="${U7S_NODE_NAME:-u7s-$(hostname)}"
    export U7S_NODE_NAME

    u7s_check_root
}

# One usernetes node per host: the working copy, podman state and node
# container are per user and per host, so a second launcher on the same host
# would tear down the first. Take a host-local lock for the life of this
# launcher (and of the service script, which inherits the descriptor), and
# refuse to start if another launcher holds it. Call this before installing
# the teardown trap, so a refused launcher does not run 'make down-v'.
u7s_lock_node() {
    local lock="${USERNETES_NODE_LOCK:-/tmp/${USERNAME}/.flux-batch-usernetes.lock}"
    mkdir -p "$(dirname "${lock}")"
    exec 9>> "${lock}"
    if ! flock -n 9; then
        error_exit "Another usernetes launcher is already running on $(hostname) (lock ${lock}). One usernetes node per host: submit usernetes jobs with exclusive nodes."
    fi
}

# Fail early, with a pointed message, if the checkout is unusable.
u7s_check_root() {
    if [[ ! -d "${USERNETES_ROOT}" ]]; then
        error_exit "USERNETES_ROOT ${USERNETES_ROOT} does not exist on $(hostname)."
    fi
    local script
    for script in usernetes-start-control-plane.sh usernetes-start-worker.sh usernetes-common.sh; do
        if [[ ! -f "${USERNETES_ROOT}/service/${script}" ]]; then
            error_exit "USERNETES_ROOT ${USERNETES_ROOT} has no service/${script}. It must be a usernetes checkout of the hetchy branch."
        fi
    done
}

# Wait for a file to appear, aborting if a child process dies first.
# u7s_wait_for_file <path> <description> [child pid] [child log]
u7s_wait_for_file() {
    local path="$1" what="$2" child="${3:-}" child_log="${4:-}"
    local waited=0
    log "⏳ Waiting for ${what}: ${path} (timeout ${USERNETES_WAIT_TIMEOUT}s)"
    while [[ ! -e "${path}" ]]; do
        if [[ -n "${child}" ]] && ! kill -0 "${child}" 2>/dev/null; then
            u7s_dump_log "${child_log}"
            error_exit "The usernetes service script (pid ${child}) exited while waiting for ${what}."
        fi
        if (( waited >= USERNETES_WAIT_TIMEOUT )); then
            u7s_dump_log "${child_log}"
            error_exit "Timed out after ${USERNETES_WAIT_TIMEOUT}s waiting for ${what}."
        fi
        sleep "${USERNETES_POLL_INTERVAL:-5}"
        waited=$((waited + ${USERNETES_POLL_INTERVAL:-5}))
    done
    log "    Found ${what}."
}

# Wait until a predicate (a function name) returns success.
# u7s_wait_for <description> <function> [child pid] [child log]
u7s_wait_for() {
    local what="$1" fn="$2" child="${3:-}" child_log="${4:-}"
    local waited=0
    log "⏳ Waiting for ${what} (timeout ${USERNETES_WAIT_TIMEOUT}s)"
    until "${fn}"; do
        if [[ -n "${child}" ]] && ! kill -0 "${child}" 2>/dev/null; then
            u7s_dump_log "${child_log}"
            error_exit "The usernetes service script (pid ${child}) exited while waiting for ${what}."
        fi
        if (( waited >= USERNETES_WAIT_TIMEOUT )); then
            u7s_dump_log "${child_log}"
            error_exit "Timed out after ${USERNETES_WAIT_TIMEOUT}s waiting for ${what}."
        fi
        sleep "${USERNETES_POLL_INTERVAL:-5}"
        waited=$((waited + ${USERNETES_POLL_INTERVAL:-5}))
    done
    log "    ${what}: done."
}

u7s_dump_log() {
    local file="${1:-}"
    if [[ -n "${file}" && -f "${file}" ]]; then
        echo "---- last 40 lines of ${file} ----" >&2
        tail -n 40 "${file}" >&2 || true
        echo "----------------------------------" >&2
    fi
}

# Best-effort teardown of this node's usernetes containers. The working copy
# lives in ${TMPDIR}/usernetes once the service script has run.
u7s_make_down() {
    if [[ -d "${TMPDIR}/usernetes" ]]; then
        log "🧹 Running 'make down-v' in ${TMPDIR}/usernetes (best effort)"
        (
            cd "${TMPDIR}/usernetes" || exit 0
            # source_env.sh restores the storage/runtime environment the
            # service scripts used, so podman sees the same state.
            [[ -f source_env.sh ]] && source ./source_env.sh
            make down-v || true
        ) || true
    fi
}
