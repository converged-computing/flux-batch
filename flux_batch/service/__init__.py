import os
import subprocess
import sys

import flux_batch.service.scribe as scribe

# Lookup of known services
services = {"flux-scribe": scribe.SERVICE_TEMPLATE}
modules = {
    "flux-scribe": {
        "startup": scribe.START_MODULE_TEMPLATE,
        "shutdown": scribe.STOP_MODULE_TEMPLATE,
        "module": scribe.MODULE_NAME,
    }
}


def write_modprobe_script(rc_path, script, args=None):
    """
    Shared function to write service file.
    """
    args = args or {}
    if not os.path.exists(rc_path):
        with open(rc_path, "w") as f:
            f.write(script.format(**args))


def ensure_modprobe_scripts(service_name: str):
    """
    Ensures rc1.d (start) and rc3.d (stop) scripts exist for the service.
    """
    if service_name not in modules:
        print("Warning: module {service_name} is not known.")
        return

    # We will add these to FLUX_MODPROBE_PATH_APPEND
    base_dir = os.path.expanduser("~/.flux-batch")
    for subdir in ["rc1.d", "rc3.d"]:
        os.makedirs(os.path.join(base_dir, subdir), exist_ok=True)

    service_func = service_name.replace("-", "_")

    # Path for rc1.d (startup)
    args = {
        "service_name": service_name,
        "service_func": service_func,
        "python_bin": sys.executable,
        "module_name": modules[service_name]["module"],
    }
    rc1_path = os.path.join(base_dir, "rc1.d", f"{service_name}.py")
    script = modules[service_name]["startup"]
    write_modprobe_script(rc1_path, script, args=args)

    # Path for rc3.d (shutdown)
    args = {"service_name": service_name, "service_func": service_func}
    rc3_path = os.path.join(base_dir, "rc3.d", f"{service_name}.py")
    script = modules[service_name]["shutdown"]
    write_modprobe_script(rc3_path, script, args=args)


def ensure_user_service(service_name: str):
    """
    Checks for the existence of a systemd service file in the user's home.
    If it doesn't exist, it creates it and reloads the daemon.
    """
    user_systemd_dir = os.path.expanduser("~/.config/systemd/user")
    os.makedirs(user_systemd_dir, exist_ok=True)
    service_path = os.path.join(user_systemd_dir, f"{service_name}.service")

    if not os.path.exists(service_path):
        if service_name in services:
            template = services[service_name]
            print(f"[*] Provisioning {service_name} at {service_path}")
            with open(service_path, "w") as f:
                f.write(template.format(python_path=sys.executable))

        else:
            print(f"[*] Service {service_name} is not known, assuming exists.")

        # Reload the user-session manager to recognize the new unit
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
