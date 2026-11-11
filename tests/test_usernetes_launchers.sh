#!/bin/bash
#
# End-to-end test of the usernetes launchers with every external piece
# stubbed: no podman, no kubernetes, no flux broker. The usernetes service
# scripts (normally in a hetchy-branch checkout), kubectl, make, and flux are
# replaced with stubs that keep "cluster state" in plain files, so this
# exercises exactly the orchestration the launchers own: startup order, the
# stale-join-command guard, readiness publication, bursting, departures, and
# teardown.
#
#   ./tests/test_usernetes_launchers.sh       # run all checks
#   ./tests/test_usernetes_launchers.sh -v    # also print launcher logs
#
set -uo pipefail

verbose=0
[[ "${1:-}" == "-v" ]] && verbose=1

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
scripts="${here}/../flux_batch/service/usernetes/script"

ROOT=$(mktemp -d /tmp/u7s-launcher-test.XXXXXX)
export STATE="${ROOT}/state"
SHARED_ROOT="${ROOT}/shared"
BIN="${ROOT}/bin"
FAKE_U7S="${ROOT}/usernetes-root"
mkdir -p "${STATE}/nodes" "${SHARED_ROOT}" "${BIN}" "${FAKE_U7S}/service" "${ROOT}/home"

checks=0
failures=0
pids=()

ok()  { checks=$((checks+1)); echo "  ✅ $1"; }
bad() { checks=$((checks+1)); failures=$((failures+1)); echo "  ❌ $1"; }

check() { # check <description> <command...>
    local what="$1"; shift
    if "$@" >/dev/null 2>&1; then ok "${what}"; else bad "${what}"; fi
}

wait_until() { # wait_until <seconds> <command...>
    local deadline=$(( $(date +%s) + $1 )); shift
    until "$@" >/dev/null 2>&1; do
        (( $(date +%s) >= deadline )) && return 1
        sleep 0.5
    done
}

cleanup() {
    for pid in "${pids[@]:-}"; do
        kill -KILL -- "-${pid}" 2>/dev/null || kill -KILL "${pid}" 2>/dev/null || true
    done
    if (( verbose )); then
        for f in "${ROOT}"/logs-*/*.log; do
            [[ -e "${f}" ]] || continue
            echo "---- ${f} ----"; cat "${f}"
        done
    fi
    rm -rf "${ROOT}"
}
trap cleanup EXIT

# ---------------------------------------------------------------------------
# Stubs: cluster state is files under $STATE/nodes/<name> holding the status.
# ---------------------------------------------------------------------------
cat > "${BIN}/kubectl" <<'EOF'
#!/bin/bash
all="$*"
case "$1 $2" in
    "get nodes")
        for f in "${STATE}"/nodes/*; do
            [[ -e "${f}" ]] || continue
            name=$(basename "${f}")
            if [[ "${all}" == *"-o name"* ]]; then
                echo "node/${name}"
            else
                echo "${name}   $(cat "${f}")   <none>   1m   v1.33.0"
            fi
        done
        ;;
    "delete node")
        rm -f "${STATE}/nodes/$3"
        ;;
esac
exit 0
EOF

cat > "${BIN}/make" <<'EOF'
#!/bin/bash
echo "make $* (from $(pwd))" >> "${STATE}/make.log"
exit 0
EOF

cat > "${BIN}/flux" <<'EOF'
#!/bin/bash
# flux hostlist --expand local
echo "cp w1"
EOF
chmod +x "${BIN}/kubectl" "${BIN}/make" "${BIN}/flux"
export PATH="${BIN}:${PATH}"

# The "usernetes checkout": stub service scripts that imitate the real ones'
# observable behavior (kubeconfig, join command, node registration, idling).
touch "${FAKE_U7S}/service/usernetes-common.sh"

cat > "${FAKE_U7S}/service/usernetes-start-control-plane.sh" <<'EOF'
#!/bin/bash
mkdir -p "${TMPDIR}/usernetes"
: > "${TMPDIR}/usernetes/source_env.sh"
echo "fake-kubeconfig" > "${TMPDIR}/usernetes/kubeconfig"
echo "echo join me" > "${USERNETES_SHARED_DIR}/join-command"
mkdir -p "${STATE}/nodes"
echo "NotReady" > "${STATE}/nodes/${U7S_NODE_NAME}"
( sleep 1; echo "Ready" > "${STATE}/nodes/${U7S_NODE_NAME}" ) &
sleep infinity
EOF

cat > "${FAKE_U7S}/service/usernetes-start-worker.sh" <<'EOF'
#!/bin/bash
[[ -f "${USERNETES_SHARED_DIR}/join-command" ]] || { echo "no join-command" >&2; exit 1; }
mkdir -p "${TMPDIR}/usernetes"
: > "${TMPDIR}/usernetes/source_env.sh"
mkdir -p "${STATE}/nodes"
echo "NotReady" > "${STATE}/nodes/${U7S_NODE_NAME}"
( sleep 1; echo "Ready" > "${STATE}/nodes/${U7S_NODE_NAME}" ) &
sleep infinity
EOF

cat > "${FAKE_U7S}/service/check-calico.sh" <<'EOF'
#!/bin/bash
echo "check-calico $* (KUBECONFIG=${KUBECONFIG:-unset})" >> "${STATE}/make.log"
exit 0
EOF
chmod +x "${FAKE_U7S}"/service/*.sh

# Environment shared by every launcher invocation
common_env=(
    STATE="${STATE}"
    PATH="${PATH}"
    HOME="${ROOT}/home"
    USERNETES_ROOT="${FAKE_U7S}"
    USERNETES_CLUSTER_NAME="test"
    USERNETES_SHARED_ROOT="${SHARED_ROOT}"
    USERNETES_WAIT_TIMEOUT=30
    USERNETES_POLL_INTERVAL=1
    USERNETES_RECONCILE_INTERVAL=1
)
SHARED="${SHARED_ROOT}/test"

launch() { # launch <pidvar> <script> <extra env...>
    local pidvar="$1" script="$2"; shift 2
    # Each simulated node gets its own host lock; "$@" may override it.
    env -i "${common_env[@]}" USERNETES_NODE_LOCK="${ROOT}/lock-${pidvar}" "$@" \
        setsid bash "${scripts}/${script}" &
    local pid=$!
    pids+=("${pid}")
    printf -v "${pidvar}" '%s' "${pid}"
}

echo "=== Stale state guard: a worker must not trust leftovers from an old cluster"
mkdir -p "${SHARED}"
echo "stale join" > "${SHARED}/join-command"
echo "old-launch-id" > "${SHARED}/launch-id"

launch worker_pid launch-worker.sh \
    USERNETES_MODE=cluster USERNETES_LAUNCH_ID=abc-123 \
    U7S_NODE_NAME=u7s-w1 TMPDIR="${ROOT}/tmp-w1" USERNETES_LOG_DIR="${ROOT}/logs-w1"
sleep 3
check "worker is waiting, has not started the service script" \
    test ! -e "${ROOT}/logs-w1/usernetes-worker.log"
check "worker launcher is still alive" kill -0 "${worker_pid}"

echo "=== Cluster mode: control plane up, worker joins, readiness published"
launch cp_pid launch-control-plane.sh \
    USERNETES_LAUNCH_ID=abc-123 USERNETES_EXPECTED_NODES=2 \
    U7S_NODE_NAME=u7s-cp TMPDIR="${ROOT}/tmp-cp" USERNETES_LOG_DIR="${ROOT}/logs-cp"

check "stale join-command was cleared and rewritten by this control plane" \
    wait_until 20 grep -q "join me" "${SHARED}/join-command"
check "launch id published" wait_until 10 grep -qx "abc-123" "${SHARED}/launch-id"
check "ready sentinel appears" wait_until 30 test -e "${SHARED}/ready"
check "control plane node in ready-nodes" grep -qx "u7s-cp" "${SHARED}/ready-nodes"
check "worker node becomes Ready in ready-nodes" \
    wait_until 20 grep -qx "u7s-w1" "${SHARED}/ready-nodes"
check "worker registered itself" wait_until 20 test -e "${SHARED}/workers/u7s-w1"
check "CNI installed once" test "$(grep -c 'make install-cni' "${STATE}/make.log")" = "1"
check "external IPs synced" grep -q "make sync-external-ip" "${STATE}/make.log"

echo "=== Batch wrapper gate: wait-for-ready.sh"
check "wait-for-ready passes once all of the job's nodes are Ready" \
    env STATE="${STATE}" PATH="${PATH}" bash "${scripts}/wait-for-ready.sh" "${SHARED}" 10

echo "=== Bursting: a worker from another job joins the existing cluster"
syncs_before=$(grep -c "make sync-external-ip" "${STATE}/make.log")
launch burst_pid launch-worker.sh \
    USERNETES_MODE=worker \
    U7S_NODE_NAME=u7s-b1 TMPDIR="${ROOT}/tmp-b1" USERNETES_LOG_DIR="${ROOT}/logs-b1"

check "burst worker becomes Ready in ready-nodes" \
    wait_until 20 grep -qx "u7s-b1" "${SHARED}/ready-nodes"
check "burst worker registered itself" wait_until 10 test -e "${SHARED}/workers/u7s-b1"
check "control plane re-synced external IPs for the new node" \
    test "$(grep -c 'make sync-external-ip' "${STATE}/make.log")" -gt "${syncs_before}"
check "calico addresses re-checked and fixed" grep -q "check-calico --fix" "${STATE}/make.log"

echo "=== Departure: the burst job ends and its node is removed"
kill -TERM "${burst_pid}" 2>/dev/null
check "node object deleted by the control plane" \
    wait_until 20 test ! -e "${STATE}/nodes/u7s-b1"
check "departure marker consumed" wait_until 10 test ! -e "${SHARED}/leaving/u7s-b1"
check "worker registration removed" test ! -e "${SHARED}/workers/u7s-b1"
check "burst node brought down (make down-v)" \
    grep -q "make down-v (from ${ROOT}/tmp-b1/usernetes)" "${STATE}/make.log"
check "burst node still in ready-nodes? no" \
    wait_until 10 bash -c "! grep -qx u7s-b1 '${SHARED}/ready-nodes'"

echo "=== One node per host: a second launcher on a busy host refuses to start"
downs_before=$(grep -c "make down-v" "${STATE}/make.log")
env -i "${common_env[@]}" USERNETES_NODE_LOCK="${ROOT}/lock-cp_pid" USERNETES_MODE=worker \
    U7S_NODE_NAME=u7s-cp TMPDIR="${ROOT}/tmp-cp" USERNETES_LOG_DIR="${ROOT}/logs-dup" \
    bash "${scripts}/launch-worker.sh"
[[ $? -ne 0 ]] && ok "second launcher on the same host exits with an error" \
    || bad "second launcher on the same host should refuse to start"
check "refused launcher says why" grep -q "already running" "${ROOT}/logs-dup/usernetes-worker-launcher.log"
check "refused launcher did not run make down-v" \
    test "$(grep -c "make down-v" "${STATE}/make.log")" = "${downs_before}"
check "control plane still alive" kill -0 "${cp_pid}"

echo "=== Teardown: the cluster job ends"
kill -TERM "${worker_pid}" 2>/dev/null
kill -TERM "${cp_pid}" 2>/dev/null
check "ready sentinel removed so late waiters fail fast" \
    wait_until 15 test ! -e "${SHARED}/ready"
check "control plane brought down (make down-v)" \
    wait_until 10 grep -q "make down-v (from ${ROOT}/tmp-cp/usernetes)" "${STATE}/make.log"
check "worker brought down (make down-v)" \
    wait_until 10 grep -q "make down-v (from ${ROOT}/tmp-w1/usernetes)" "${STATE}/make.log"

echo "=== Failure paths"
env -i "${common_env[@]}" USERNETES_WAIT_TIMEOUT=2 USERNETES_MODE=worker \
    USERNETES_CLUSTER_NAME=missing U7S_NODE_NAME=u7s-x \
    TMPDIR="${ROOT}/tmp-x" USERNETES_LOG_DIR="${ROOT}/logs-x" \
    bash "${scripts}/launch-worker.sh"
[[ $? -ne 0 ]] && ok "burst worker times out when the cluster does not exist" \
    || bad "burst worker should fail when the cluster does not exist"

env -i "${common_env[@]}" USERNETES_ROOT="${ROOT}/nonexistent" \
    TMPDIR="${ROOT}/tmp-x" USERNETES_LOG_DIR="${ROOT}/logs-x" \
    bash "${scripts}/launch-worker.sh"
[[ $? -ne 0 ]] && ok "launcher fails fast when USERNETES_ROOT is missing" \
    || bad "launcher should fail when USERNETES_ROOT is missing"

echo
echo "${checks} checks, ${failures} failures"
exit "$(( failures > 0 ))"
