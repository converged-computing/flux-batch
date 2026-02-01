import os

import flux_batch


def get_script(name):
    """
    Get a script by name
    """
    # Find the path to the installed script
    base_path = os.path.dirname(os.path.abspath(flux_batch.__file__))
    script_path = os.path.join(base_path, "script", name)
    if not os.path.exists(script_path):
        print(f"Warning: script {name} does not exist")
        return
    return script_path
