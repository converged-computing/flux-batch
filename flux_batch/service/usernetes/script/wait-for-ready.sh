#!/bin/bash
#
# wait-for-ready.sh - gate the batch job's workload on the usernetes cluster.
#
# flux-batch renders this at the top of the batch wrapper script, before any
# user jobs, so work only starts once the cluster is ready AND every node of
# THIS batch job is Ready in it (in a burst job, that means every bursted
# worker has joined). Runs on rank 0 of the batch instance; state comes from
# the cluster directory on the shared filesystem.
#
# Usage: wait-for-ready.sh <shared dir> [timeout seconds]

set -euo pipefail

shared_dir="${1:?Usage: wait-for-ready.sh <shared dir> [timeout seconds]}"
timeout="${2:-3600}"

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - INFO - [usernetes] $1"
}

# The hostnames of this batch instance; each registers as node u7s-<hostname>.
hosts=$(flux hostlist --expand local 2>/dev/null || hostname)

waited=0
wait_step=5
wait_for() {
    local what="$1" check="$2"
    log "⏳ Waiting for ${what} (up to $((timeout - waited))s more)"
    until eval "${check}"; do
        if (( waited >= timeout )); then
            echo "ERROR: [usernetes] timed out after ${timeout}s waiting for ${what}." >&2
            echo "       Check the launcher logs under /tmp/\$USER on each node." >&2
            exit 1
        fi
        sleep "${wait_step}"
        waited=$((waited + wait_step))
    done
    log "    ${what}: done."
}

wait_for "cluster to be ready (${shared_dir}/ready)" "[[ -e '${shared_dir}/ready' ]]"

for host in ${hosts}; do
    node="u7s-${host}"
    wait_for "node ${node} to be Ready" "grep -qx '${node}' '${shared_dir}/ready-nodes' 2>/dev/null"
done

log "🎉 Usernetes cluster is ready on every node of this job."
