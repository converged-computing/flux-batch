#!/bin/bash

# Shared library of functions
source "$(dirname "$0")/usernetes-common.sh"

# Configure
USERNETES_CONTAINER_TECH=${1:-"podman"}
USERNETES_JOB_ID=${2:-"default"}

export USERNAME=$(whoami)
export TMPDIR="/tmp/$USERNAME"
export TMPDIR_LOG=/tmp

SHARED_JOIN_COMMAND_DIR=$(get_shared_join_command_dir "${USERNETES_JOB_ID}")

# Write to logging file. We assume one kubelet (control plane or worker) per node
LOG_FILE=${TMPDIR_LOG}/control-plane.log
USERNETES_LOGFILE=${3:-"${LOG_FILE}"}
rm -rf $USERNETES_LOGFILE
exec &> "$USERNETES_LOGFILE"
# trap 'rm -f "$USERNETES_LOGFILE"' EXIT

USERNETES_TEMPLATE_PATH=/usr/workspace/usernetes/usernetes-calico

log "🎬 Starting Usernetes Control Plane Setup"
log "🪪 Usernetes job id is ${USERNETES_JOB_ID}"

# Shared setup (also done by worker)
setup_environment
install_required_tools
setup_container_runtime "${USERNETES_CONTAINER_TECH}"
prepare_usernetes_directory "${USERNETES_TEMPLATE_PATH}"
cleanup_previous_run
build_usernetes_image

# Control-plane specific
log "   ⬆️ Bringing up the Usernetes node with 'make up'"
make up || error_exit "Failed 'make up' for control plane."
sleep 3

log "🔐 Initializing the cluster with 'make kubeadm-init'"
make kubeadm-init || error_exit "Failed 'make kubeadm-init'."
sleep 3

log "🥷 Creating kubeconfig with 'make kubeconfig'"
make kubeconfig || error_exit "Failed 'make kubeconfig'."
export KUBECONFIG="${TMPDIR}/usernetes/kubeconfig"
log "   KUBECONFIG set to: ${KUBECONFIG}"
chmod 600 "${KUBECONFIG}"
sleep 3

# 3. Untaint and Label the Control Plane Node
log "🍑 Untainting and labeling control plane node..."
control_plane_node=""
for i in {1..5}; do
    control_plane_node=$(kubectl get nodes -l node-role.kubernetes.io/control-plane -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
    if [[ -n "$control_plane_node" ]]; then break; fi
    log "   Control plane node not ready, retrying... ($i/5)"
    sleep 5
done
[[ -n "$control_plane_node" ]] || error_exit "Could not find control plane node."
log "   Found control plane node: ${control_plane_node}"

kubectl taint node "${control_plane_node}" node-role.kubernetes.io/control-plane:NoSchedule- || log "   WARN: Failed to untaint node."
kubectl label node "${control_plane_node}" node.kubernetes.io/exclude-from-external-load-balancers- || log "   WARN: Failed to remove label."

log "📄 Current Kubernetes Nodes:"
kubectl get nodes -o wide

# 4. Generate and Share the Join Command
log "🔗 Generating join command and sharing..."
make join-command || error_exit "Failed to generate join command."
mkdir -p "${SHARED_JOIN_COMMAND_DIR}"
cp join-command "${SHARED_JOIN_COMMAND_DIR}/join-command"
chmod +x "${SHARED_JOIN_COMMAND_DIR}/join-command"
log "   Join command copied to: ${SHARED_JOIN_COMMAND_DIR}/join-command"

# Generate the environment sourcing script
log "📝 Creating source_env.sh for user convenience..."
cat <<EOF > source_env.sh
#!/bin/bash
export PATH="${LOCAL_BIN_DIR}:\$PATH"
export KUBECONFIG="${KUBECONFIG}"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR}"
source <(kubectl completion bash)
EOF

# 5. Finalize
log "🎉 Usernetes Control Plane setup complete."
log "   To use this cluster, run: export KUBECONFIG=${KUBECONFIG}"
log "🚀 Service will now idle indefinitely. Process ID: $$"
sleep infinity
