#!/bin/bash
#
# launch-control-plane.sh - flux-batch launcher for the usernetes control plane.
#
# Runs on rank 0 of the batch job (cluster mode). Thin orchestration around
# <USERNETES_ROOT>/service/usernetes-start-control-plane.sh, which does all of
# the per-node work (podman storage, image build, kubeadm init, join command).
# This launcher adds what a multi-node batch job needs on top:
#
#   1. A per-cluster state directory on the shared filesystem, cleared of any
#      stale join command before workers can see it (guarded by a launch id
#      rendered into both the leader and worker commands at submit time).
#   2. Waiting for the expected number of nodes to register, then running
#      'make install-cni' and 'make sync-external-ip' (nodes stay NotReady
#      until the CNI is installed, and it should be installed once, after
#      the initial nodes have joined).
#   3. A 'ready' sentinel plus a 'ready-nodes' list that workers and the batch
#      wrapper gate on.
#   4. A reconcile loop for bursting: when new nodes join from another job,
#      re-run sync-external-ip and restart calico-node where it autodetected
#      the wrong address; when workers leave, delete their node objects.
#
# See launch-common.sh for every knob.

set -euo pipefail

here="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
# shellcheck source=launch-common.sh
source "${here}/launch-common.sh"

u7s_setup_env

# Our own output and the service script's output both go under the log dir.
LAUNCHER_LOG="${USERNETES_LOG_DIR}/usernetes-control-plane-launcher.log"
SERVICE_LOG="${USERNETES_LOG_DIR}/usernetes-control-plane.log"
exec &>> "${LAUNCHER_LOG}"

log "🎬 Usernetes control plane launcher starting on $(hostname)"
u7s_lock_node
log "    Cluster:  ${USERNETES_CLUSTER_NAME} (${USERNETES_SHARED_DIR})"
log "    Checkout: ${USERNETES_ROOT}"
log "    Expecting ${USERNETES_EXPECTED_NODES} node(s) before installing the CNI"

# ---------------------------------------------------------------------------
# Cluster state directory: clear anything a previous cluster of the same name
# left behind, so a worker of THIS job can never pick up a stale join command.
# The launch id was generated at submit time and rendered into both the leader
# and the worker commands; workers wait for this exact id before they trust
# the join command.
# ---------------------------------------------------------------------------
mkdir -p "${USERNETES_SHARED_DIR}"/{workers,leaving}
rm -f "${USERNETES_SHARED_DIR}"/{ready,ready-nodes,join-command,launch-id}
rm -f "${USERNETES_SHARED_DIR}"/workers/* "${USERNETES_SHARED_DIR}"/leaving/* 2>/dev/null || true

cat > "${USERNETES_SHARED_DIR}/meta" <<EOF
cluster=${USERNETES_CLUSTER_NAME}
leader=$(hostname)
leader_node=${U7S_NODE_NAME}
flux_job=${FLUX_JOB_ID:-unknown}
started=$(date '+%Y-%m-%d %H:%M:%S')
EOF

if [[ -n "${USERNETES_LAUNCH_ID:-}" ]]; then
    echo "${USERNETES_LAUNCH_ID}" > "${USERNETES_SHARED_DIR}/launch-id"
fi

# ---------------------------------------------------------------------------
# Teardown: kill the service script's process group, bring the node down, and
# remove the sentinel so late waiters fail fast instead of hanging.
# ---------------------------------------------------------------------------
child=""
teardown() {
    local code=$?
    trap - EXIT TERM INT HUP
    log "🛑 Control plane launcher tearing down (exit code ${code})"
    rm -f "${USERNETES_SHARED_DIR}"/{ready,launch-id} 2>/dev/null || true
    if [[ -n "${child}" ]] && kill -0 "${child}" 2>/dev/null; then
        kill -TERM -- "-${child}" 2>/dev/null || kill -TERM "${child}" 2>/dev/null || true
    fi
    u7s_make_down
    exit "${code}"
}
trap teardown EXIT TERM INT HUP

# ---------------------------------------------------------------------------
# Start the usernetes control plane service script. setsid gives it its own
# process group so teardown can kill everything it spawned.
# ---------------------------------------------------------------------------
log "🚀 Starting ${USERNETES_ROOT}/service/usernetes-start-control-plane.sh (log: ${SERVICE_LOG})"
rm -f "${SERVICE_LOG}"
setsid bash "${USERNETES_ROOT}/service/usernetes-start-control-plane.sh" \
    "${USERNETES_CONTAINER_TECH:-podman}" &>> "${SERVICE_LOG}" &
child=$!
log "    Service script running as pid ${child}"

# The service script creates the working copy, builds images, runs kubeadm
# init, writes the kubeconfig, and copies the join command to the shared dir.
export KUBECONFIG="${TMPDIR}/usernetes/kubeconfig"
export PATH="${HOME}/.local/bin:${PATH}"

u7s_wait_for_file "${KUBECONFIG}" "kubeconfig" "${child}" "${SERVICE_LOG}"
u7s_wait_for_file "${USERNETES_SHARED_DIR}/join-command" "join command" "${child}" "${SERVICE_LOG}"

# ---------------------------------------------------------------------------
# Wait for the initial nodes, install the CNI, sync addresses, wait for Ready.
# ---------------------------------------------------------------------------
count_registered() {
    local n
    n=$(kubectl get nodes --no-headers 2>/dev/null | wc -l)
    (( n >= USERNETES_EXPECTED_NODES ))
}
count_ready() {
    local n
    n=$(kubectl get nodes --no-headers 2>/dev/null | awk '$2 == "Ready"' | wc -l)
    (( n >= USERNETES_EXPECTED_NODES ))
}

u7s_wait_for "${USERNETES_EXPECTED_NODES} node(s) to register" count_registered "${child}" "${SERVICE_LOG}"

log "🔌 Installing the CNI and syncing node addresses"
(
    cd "${TMPDIR}/usernetes"
    [[ -f source_env.sh ]] && source ./source_env.sh
    make install-cni
    make sync-external-ip
) || error_exit "Failed to install the CNI / sync external IPs. See ${LAUNCHER_LOG}."

u7s_wait_for "${USERNETES_EXPECTED_NODES} node(s) to be Ready" count_ready "${child}" "${SERVICE_LOG}"

# ---------------------------------------------------------------------------
# Publish readiness: ready-nodes lists the Ready node names (refreshed by the
# reconcile loop), and the ready sentinel unblocks workers and batch wrappers.
# ---------------------------------------------------------------------------
publish_ready_nodes() {
    kubectl get nodes --no-headers 2>/dev/null \
        | awk '$2 == "Ready" {print $1}' > "${USERNETES_SHARED_DIR}/.ready-nodes.tmp" \
        && mv "${USERNETES_SHARED_DIR}/.ready-nodes.tmp" "${USERNETES_SHARED_DIR}/ready-nodes"
}

publish_ready_nodes
touch "${USERNETES_SHARED_DIR}/ready"
log "🎉 Cluster '${USERNETES_CLUSTER_NAME}' is ready."
log "    KUBECONFIG=${KUBECONFIG}"
kubectl get nodes -o wide 2>/dev/null || true

# ---------------------------------------------------------------------------
# Reconcile loop, for the lifetime of the batch job:
#   - Burst arrivals: when the node set grows, calico-node on the new nodes
#     autodetected its address before sync-external-ip could cover them, so
#     re-sync and let check-calico.sh --fix restart the ones that are wrong.
#   - Departures: worker launchers leave a marker in leaving/ on teardown;
#     delete those node objects so the cluster does not accumulate NotReady
#     corpses across burst jobs.
# ---------------------------------------------------------------------------
last_nodes=$(kubectl get nodes -o name 2>/dev/null | sort || true)
log "👀 Reconciling every ${USERNETES_RECONCILE_INTERVAL}s (burst arrivals and departures)"
while true; do
    sleep "${USERNETES_RECONCILE_INTERVAL}"

    if ! kill -0 "${child}" 2>/dev/null; then
        u7s_dump_log "${SERVICE_LOG}"
        error_exit "The control plane service script (pid ${child}) exited."
    fi

    # Departures first, so a node that left does not count as a change below.
    for marker in "${USERNETES_SHARED_DIR}"/leaving/*; do
        [[ -e "${marker}" ]] || continue
        node=$(basename "${marker}")
        log "👋 Node ${node} is leaving; deleting it from the cluster"
        kubectl delete node "${node}" --ignore-not-found 2>/dev/null || true
        rm -f "${marker}" "${USERNETES_SHARED_DIR}/workers/${node}"
    done

    nodes_now=$(kubectl get nodes -o name 2>/dev/null | sort || true)
    if [[ "${nodes_now}" != "${last_nodes}" ]]; then
        log "🔄 Node set changed; re-syncing external IPs"
        (
            cd "${TMPDIR}/usernetes"
            [[ -f source_env.sh ]] && source ./source_env.sh
            make sync-external-ip || true
            # Calico-specific: restart calico-node where it kept the wrong
            # address (it only autodetects at startup).
            if [[ "${CNI:-${USERNETES_CNI:-calico}}" == "calico" ]]; then
                bash "${USERNETES_ROOT}/service/check-calico.sh" --fix || true
            fi
        ) || log "WARN: reconcile of the new node set failed; will retry on the next change"
        last_nodes="${nodes_now}"
    fi

    publish_ready_nodes || true
done
