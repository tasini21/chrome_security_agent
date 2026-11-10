import os
import socket
import subprocess
from pathlib import Path

flask_process = None
LOG_FILE = Path("logs/flask_server.log")

def start_flask_server() -> str:
    """Start the Flask development server in the background.
    Returns the local IP address and port to access the server."""

    global flask_process

    port = 5000

    if flask_process and flask_process.poll() is None:
        return f"Flask server is already running at http://{get_local_ip()}:{port}"

    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["FLASK_APP"] = "app.py"
    env["PYTHONUNBUFFERED"] = "1"

    log_handle = open(LOG_FILE, "a", encoding="utf-8")

    flask_process = subprocess.Popen(
        ["flask", "run", "--host=0.0.0.0", f"--port={port}"],
        env=env,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        start_new_session=True
    )

    return (
        f"Flask server started (PID: {flask_process.pid}).\n"
        f"Local URL: http://{get_local_ip()}:{port}"
    )


def get_local_ip() -> str:
    """Get the machine's local network IP address."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    finally:
        s.close()

if __name__ == "__main__":
    print(start_flask_server())