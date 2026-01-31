import os
import subprocess
import sys

from .scribe import SERVICE_TEMPLATE as scribe_template

# Lookup of known services
services = {"scribe": scribe_template}


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
