#!/bin/bash
# usernetes-common.sh - Shared functions for Usernetes setup

# This script is meant to be sourced, not executed directly.
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    echo "This script should be sourced, not executed directly."
    exit 1
fi

# A robust shell script practice
set -euo pipefail

# Write to /tmp but scoped to the username
export USERNAME=$(whoami)
export TMPDIR="/tmp/${USERNAME}"

# Logging
log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - INFO - $1"
}

error_exit() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - ERROR - $1" >&2
    exit 1
}

# Environment and path

setup_environment() {
    log "🦋 Setting up core environment..."

    local USERNAME=$(whoami)

    # 1. Ensure HOME is correctly set
    if [[ -z "${HOME:-}" || ! -d "${HOME}" ]]; then
        local user_home_dir=$(getent passwd "${USERNAME}" | cut -d: -f6)
        if [[ -z "${user_home_dir}" || ! -d "${user_home_dir}" ]]; then
            error_exit "Cannot determine user's home directory. HOME is not set or invalid."
        fi
        export HOME="${user_home_dir}"
        log "   WARNING: HOME was not set. Derived as: ${HOME}"
    fi

    # Set up a user-specific temporary directory
    # We don't want to use /var because that is a memory based fs
    export TMPDIR="/tmp/${USERNAME}"
    log "   Temporary directory set to: ${TMPDIR}"
    mkdir -p "${TMPDIR}"

    # 3. Add user's local bin to PATH for our tools
    export LOCAL_BIN_DIR="${HOME}/.local/bin"
    mkdir -p "${LOCAL_BIN_DIR}"
    export PATH="${LOCAL_BIN_DIR}:${PATH}"
    log "   User bin directory added to PATH: ${LOCAL_BIN_DIR}"
}

get_shared_join_command_dir() {
    flux_id=${1:-"default"}
    export USERNAME=$(whoami)
    if [[ -z "${HOME:-}" || ! -d "${HOME}" ]]; then
        local user_home_dir=$(getent passwd "${USERNAME}" | cut -d: -f6)
        if [[ -z "${user_home_dir}" || ! -d "${user_home_dir}" ]]; then
            error_exit "Cannot determine user's home directory. HOME is not set or invalid."
        fi
        export HOME="${user_home_dir}"
    fi
    SHARED_JOIN_COMMAND_DIR="${HOME}/.usernetes/join-commands/${flux_id}"
    mkdir -p ${SHARED_JOIN_COMMAND_DIR}
    echo "${SHARED_JOIN_COMMAND_DIR}"
}

# Dependencies

install_dependency() {
    local name="$1"
    local install_command="$2"

    if ! command -v "${name}" > /dev/null; then
        log "   Installing ${name}..."
        # Execute the provided install command string
        if eval "${install_command}"; then
            log "      ${name} installed to ${LOCAL_BIN_DIR}/${name}"
        else
            error_exit "${name} installation failed."
        fi
    else
        log "   ${name} found at: $(command -v ${name})"
    fi
    command -v "${name}" > /dev/null || error_exit "${name} not found after installation attempt."
}

install_required_tools() {
    log "👀 Checking for required tools (kubectl, yq)..."
    local kubectl_install_cmd='curl -sSfLO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl" && chmod +x ./kubectl && mv ./kubectl "${LOCAL_BIN_DIR}/"'
    local yq_install_cmd='YQ_VERSION=v4.2.0; YQ_PLATFORM=linux_amd64; wget https://github.com/mikefarah/yq/releases/download/${YQ_VERSION}/yq_${YQ_PLATFORM} -O "${LOCAL_BIN_DIR}/yq" && chmod +x "${LOCAL_BIN_DIR}/yq"'

    install_dependency "kubectl" "${kubectl_install_cmd}"
    install_dependency "yq" "${yq_install_cmd}"
}

# Container Runtime

setup_container_runtime() {
    local tech="$1"
    log "📦 Configuring container runtime: ${tech}"

    export CONTAINER_TECHNOLOGY="${tech}"
    export CONTAINER_ENGINE="${tech}"

    log "   🔎 Checking if ${tech} is in PATH..."
    if ! command -v "${tech}" > /dev/null; then
        error_exit "${tech} not found. Please ensure it is installed."
    fi
    log "   Found ${tech} at: $(command -v ${tech})"

    # Site-specific podman setup
    if [[ "${tech}" == "podman" && -x "/collab/usr/gapps/lcweg/containers/scripts/enable-podman.sh" ]]; then
        log "   Running site-specific enable-podman.sh script..."
        if ! bash /collab/usr/gapps/lcweg/containers/scripts/enable-podman.sh vfs; then
            log "   WARNING: enable-podman.sh script failed. Podman might not be configured correctly."
        fi
    fi

    log "   Ensuring buildah is available for unshare cleanup..."
    if command -v buildah > /dev/null; then
        log "   Running buildah unshare rm -rf ${TMPDIR}/* (if exists)"
        # Be strategic about cleanup so we don't remove logs we just created...
        buildah unshare rm -rf "${TMPDIR}/usernetes"* "${TMPDIR}/config"* "${TMPDIR}/buildah"* "${TMPDIR}/run-"* || log "   buildah unshare cleanup command failed (this may be okay)."
    else
        log "   WARNING: buildah not found. Skipping unshare cleanup."
    fi
}

# Usernetes

prepare_usernetes_directory() {
    local template_path="$1"
    log "🎬 Preparing Usernetes workspace..."

    if [[ ! -d "${template_path}" ]]; then
       error_exit "Usernetes template path does not exist: ${template_path}"
    fi

    # Set up a clean XDG runtime directory
    export XDG_RUNTIME_DIR="${TMPDIR}/.usernetes/runtime"
    log "   XDG_RUNTIME_DIR set to: ${XDG_RUNTIME_DIR}"
    rm -rf "${XDG_RUNTIME_DIR}"
    mkdir -p "${XDG_RUNTIME_DIR}"

    log "   Copying Usernetes template from ${template_path}"
    cp -R "${template_path}" "${TMPDIR}/usernetes"
    cd "${TMPDIR}/usernetes"

    # Allow filesystem operations to settle if needed
    sleep 3
    log "   Changed directory to: $(pwd)"
}

build_usernetes_image() {
    log "👷 Building Usernetes container image 'usernetes_node'..."
    if ! "${CONTAINER_ENGINE}" build --userns-uid-map=0:0:1 --userns-uid-map=1:1:1999 --userns-uid-map=65534:2000:2 -f ./Dockerfile -t usernetes_node .; then
        error_exit "Failed to build 'usernetes_node' container image."
    fi
}

cleanup_previous_run() {
    log "🧹 Cleaning up old networks or volumes (best effort)..."
    network_name=$(echo usernetes_$(hostname))
    "${CONTAINER_ENGINE}" network disconnect usernetes_$(hostname) usernetes_node_1 -f || true
    "${CONTAINER_ENGINE}" network disconnect usernetes_default usernetes_node_1 -f || true
    make down-v || log "   'make down-v' failed, possibly because nothing was running."
    "${CONTAINER_ENGINE}" network rm usernetes_default -f || true
    "${CONTAINER_ENGINE}" volume rm usernetes_node-var -f || true
    "${CONTAINER_ENGINE}" volume rm usernetes_node-opt -f || true
    "${CONTAINER_ENGINE}" volume rm usernetes_node-etc -f || true
}

# Orchesetration

publish_join_command() {
    local job_id="$1"
    local join_command_file="$2"

    # Default to filesystem if not set. Valid options: archive, filesystem
    local sync_method=${USERNETES_SYNC_METHOD:-"filesystem"}
    log "   Using sync method: ${sync_method}"

    if [[ "${sync_method}" == "archive" ]]; then
        if ! command -v flux > /dev/null; then
            error_exit "USERNETES_SYNC_METHOD is 'archive' but 'flux' command is not available."
        fi

        local archive_name="join-cmd-archive-${job_id}"
        log "   Archiving join command into Flux KVS named: ${archive_name}"

        # -n sets the archive name
        # -C changes to the directory so we only archive the filename, not the full path
        flux archive create -n "${archive_name}" -C "$(dirname "${join_command_file}")" "$(basename "${join_command_file}")"
        log "   Archive created successfully."

    # Filesystem method
    else
        local shared_dir="${HOME}/.usernetes/join-commands/${job_id}"
        log "   Sharing join command via filesystem at: ${shared_dir}"
        mkdir -p "${shared_dir}"
        cp "${join_command_file}" "${shared_dir}/join-command"
        chmod 600 "${shared_dir}/join-command"
    fi
}

wait_for_join_command() {
    local join_file=${1:-"${HOME}/.usernetes/join-commands/${job_id}/join-command"}
    local job_id=${2:-"ohno"}

    local sync_method=${USERNETES_SYNC_METHOD:-"filesystem"}
    log "   Using sync method: ${sync_method}"
    log "   Join file is ${join_file}"

    if [[ "${sync_method}" == "archive" ]]; then
        if ! command -v flux > /dev/null; then
            error_exit "USERNETES_SYNC_METHOD is 'archive' but 'flux' command is not available."
        fi

        # TODO use FLUX_ENCLOSING_ID
        local archive_name="join-cmd-archive-${job_id}"
        log "   Waiting for Flux archive '${archive_name}' to be created..."

        # --waitcreate causes this command to BLOCK until the control plane creates the archive
        # -C ensures it drops the file into our requested output directory
        # flux archive extract -n "${archive_name}" --waitcreate --overwrite -C "$(dirname "${output_file}")"

        log "   Archive extracted successfully."

    else # Filesystem method
        log "   Polling for join command file: ${join_file}..."
        while [[ ! -f "${join_file}" ]]; do
            sleep 2
        done
        log "   Join command file found."
    fi
}
