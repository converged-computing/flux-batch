#!/bin/bash
#
# launch-worker.sh - flux-batch launcher for a usernetes worker.
#
# Runs on ranks >0 of a cluster-mode batch job, and on EVERY rank of a burst
# job (USERNETES_MODE=worker), where all nodes join an existing control plane
# identified by USERNETES_CLUSTER_NAME. Thin orchestration around
# <USERNETES_ROOT>/service/usernetes-start-worker.sh:
#
#   1. Wait for the control plane's join command. In cluster mode the wait is
#      guarded by the launch id both commands received at submit time, so a
#      stale join command from a previous cluster of the same name is never
#      trusted. In burst mode the cluster must already be 'ready'.
#   2. Run the usernetes worker service script (storage, image build,
#      kubeadm join) and confirm this node shows up as Ready, which the
#      control plane publishes in ready-nodes.
#   3. Register in workers/, and on teardown leave a marker in leaving/ so the
#      control plane's reconcile loop deletes the node object.
#
# See launch-common.sh for every knob.

set -euo pipefail

here="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
# shellcheck source=launch-common.sh
source "${here}/launch-common.sh"

u7s_setup_env
export USERNETES_MODE="${USERNETES_MODE:-cluster}"

LAUNCHER_LOG="${USERNETES_LOG_DIR}/usernetes-worker-launcher.log"
SERVICE_LOG="${USERNETES_LOG_DIR}/usernetes-worker.log"
exec &>> "${LAUNCHER_LOG}"

log "🎬 Usernetes worker launcher starting on $(hostname) (node ${U7S_NODE_NAME}, mode ${USERNETES_MODE})"
u7s_lock_node
log "    Cluster:  ${USERNETES_CLUSTER_NAME} (${USERNETES_SHARED_DIR})"
log "    Checkout: ${USERNETES_ROOT}"

# ---------------------------------------------------------------------------
# Wait for a join command we can trust.
# ---------------------------------------------------------------------------
if [[ "${USERNETES_MODE}" == "cluster" ]]; then
    # Same-job worker: only trust state written by OUR control plane. The
    # leader clears the cluster directory and then writes our launch id, so
    # once the id matches, the join command that appears is the fresh one.
    # (Without a launch id - a manual run - we can only wait for the join
    # command itself. Do NOT wait for 'ready' here: in cluster mode the ready
    # sentinel appears only after the workers have joined.)
    if [[ -n "${USERNETES_LAUNCH_ID:-}" ]]; then
        launch_id_matches() {
            [[ -f "${USERNETES_SHARED_DIR}/launch-id" ]] \
                && [[ "$(cat "${USERNETES_SHARED_DIR}/launch-id" 2>/dev/null)" == "${USERNETES_LAUNCH_ID}" ]]
        }
        u7s_wait_for "the control plane of this job (launch id ${USERNETES_LAUNCH_ID})" launch_id_matches
    fi
else
    # Burst worker: the target cluster must already exist and be ready.
    u7s_wait_for_file "${USERNETES_SHARED_DIR}/ready" "existing cluster '${USERNETES_CLUSTER_NAME}' to be ready"
fi
u7s_wait_for_file "${USERNETES_SHARED_DIR}/join-command" "join command"

# ---------------------------------------------------------------------------
# Teardown: tell the control plane we are leaving, then kill the service
# script's process group and bring the node down.
# ---------------------------------------------------------------------------
child=""
teardown() {
    local code=$?
    trap - EXIT TERM INT HUP
    log "🛑 Worker launcher tearing down (exit code ${code})"
    mkdir -p "${USERNETES_SHARED_DIR}/leaving" 2>/dev/null || true
    touch "${USERNETES_SHARED_DIR}/leaving/${U7S_NODE_NAME}" 2>/dev/null || true
    rm -f "${USERNETES_SHARED_DIR}/workers/${U7S_NODE_NAME}" 2>/dev/null || true
    if [[ -n "${child}" ]] && kill -0 "${child}" 2>/dev/null; then
        kill -TERM -- "-${child}" 2>/dev/null || kill -TERM "${child}" 2>/dev/null || true
    fi
    u7s_make_down
    exit "${code}"
}
trap teardown EXIT TERM INT HUP

# ---------------------------------------------------------------------------
# Start the usernetes worker service script (storage, build, kubeadm join).
# ---------------------------------------------------------------------------
log "🚀 Starting ${USERNETES_ROOT}/service/usernetes-start-worker.sh (log: ${SERVICE_LOG})"
rm -f "${SERVICE_LOG}"
setsid bash "${USERNETES_ROOT}/service/usernetes-start-worker.sh" \
    "${USERNETES_CONTAINER_TECH:-podman}" &>> "${SERVICE_LOG}" &
child=$!
log "    Service script running as pid ${child}"

# The control plane publishes Ready node names in ready-nodes; wait for ours.
node_is_ready() {
    grep -qx "${U7S_NODE_NAME}" "${USERNETES_SHARED_DIR}/ready-nodes" 2>/dev/null
}
u7s_wait_for "node ${U7S_NODE_NAME} to be Ready in the cluster" node_is_ready "${child}" "${SERVICE_LOG}"

mkdir -p "${USERNETES_SHARED_DIR}/workers"
touch "${USERNETES_SHARED_DIR}/workers/${U7S_NODE_NAME}"
log "🎉 Worker ${U7S_NODE_NAME} joined cluster '${USERNETES_CLUSTER_NAME}' and is Ready."

# Idle for the lifetime of the batch job; the service script itself sleeps.
# If it dies, report and tear down rather than idling silently.
while kill -0 "${child}" 2>/dev/null; do
    sleep "${USERNETES_RECONCILE_INTERVAL}"
done
u7s_dump_log "${SERVICE_LOG}"
error_exit "The worker service script (pid ${child}) exited."
