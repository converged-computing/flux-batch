#!/bin/bash

set -euo pipefail

# Shared library of functions
source "$(dirname "$0")/usernetes-common.sh"

# These are variables we likely will change
# LC only supplies podman
USERNETES_CONTAINER_TECH=${1:-"podman"}
USERNETES_JOB_ID=${2:-"default"}

# Write to /tmp but scoped to the username
export USERNAME=$(whoami)
export TMPDIR="/tmp/${USERNAME}"
export TMPDIR_LOG=/tmp

# Write to logging file. We assume one kubelet (control plane or worker) per node
USERNETES_LOGFILE=${TMPDIR_LOG}/worker.log
rm -rf $USERNETES_LOGFILE
exec &> "$USERNETES_LOGFILE"
# trap 'rm -f "$USERNETES_LOGFILE"' EXIT

log "🪪 Usernetes job id is ${USERNETES_JOB_ID}"
USERNETES_TEMPLATE_PATH=/usr/workspace/usernetes/usernetes-calico
SHARED_JOIN_COMMAND_DIR=$(get_shared_join_command_dir "${USERNETES_JOB_ID}")
log "🪪 Usernetes shared join directory is ${SHARED_JOIN_COMMAND_DIR}"


USERNETES_TEMPLATE_PATH=/usr/workspace/usernetes/usernetes-calico
log "🎬 Starting Usernetes Worker Setup"

# Shared setup (also done by worker)
setup_environment
install_required_tools
setup_container_runtime "${USERNETES_CONTAINER_TECH}"
prepare_usernetes_directory "${USERNETES_TEMPLATE_PATH}"
cleanup_previous_run
build_usernetes_image

# Control-plane specific
log "   ⬆️ Bringing up the Usernetes node with 'make up'"
make up || error_exit "Failed 'make up' for worker."
sleep 3

# We need to wait for the join command before continuing
join_path=${SHARED_JOIN_COMMAND_DIR}/join-command
wait_for_join_command $join_path

# Now inside the copied template
cd "${TMPDIR}/usernetes"
sleep 3

# Copy the join-command
cp "${join_path}" join-command
chmod +x join-command

log "🥷 Joining cluster with make kubeadm-join'"
if ! make kubeadm-join; then
    error_exit "Failed 'make kubeadm-join'."
fi

log "🎉 Usernetes worker node setup complete."
log "🚀 Service will now idle indefinitely. Process ID: $$"

# Make a file to easily source to get environment
cat <<EOF > source_env.sh
#!/bin/bash
export PATH=~/.local/bin:$PATH
export XDG_RUNTIME_DIR=$TMPDIR/.usernetes/runtime
EOF

# Keep the script running so systemd considers the service active.
# The actual k8s processes are managed by containerd/kubelet inside the usernetes_node container.
sleep infinity
