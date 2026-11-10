import signal
import socket
import os
import time
from typing import Optional

import ollama
import requests
from bs4 import BeautifulSoup
from ddgs import DDGS
from langchain_core.tools import tool
import subprocess
from pathlib import Path

LOG_FILE = Path("logs/flask_server.log")
flask_process = None
PORT = 5000

############## Helpers #################################################################################################

def _stop_server() -> bool:
    """Stop the server if running. Returns True if something was stopped."""
    global flask_process

    if flask_process is None or flask_process.poll() is not None:
        flask_process = None
        return False

    try:
        # start_new_session=True makes the pid the process-group id,
        # so this also kills any child processes Flask spawned
        os.killpg(flask_process.pid, signal.SIGTERM)
        flask_process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        os.killpg(flask_process.pid, signal.SIGKILL)
        flask_process.wait()
    except ProcessLookupError:
        pass

    flask_process = None
    return True

def _wait_for_port(port: int, timeout: float = 10.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if flask_process.poll() is not None:
            return False  # crashed on startup
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.3)
    return False

def _tail_log(lines: int = 15) -> str:
    try:
        return "\n".join(LOG_FILE.read_text(encoding="utf-8").splitlines()[-lines:])
    except OSError:
        return "(no log available)"

def _get_local_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()

#######################################################################################################################

@tool
def search_internet(query: str) -> str:
    """
    Searches the internet using DuckDuckGo to perform research, understand error messages, API documentations and so on.
    Returns top web results with links.
    """
    try:
        with DDGS() as ddgs:
            results = [r for r in ddgs.text(query, max_results=5)]
        if not results:
            return "No web results found for this query."

        output = []
        for i, res in enumerate(results, 1):
            output.append(f"[{i}] Title: {res['title']}\nURL: {res['href']}\nSnippet: {res['body']}\n")
        return "\n".join(output)
    except Exception as e:
        return f"Error executing web search: {str(e)}"

@tool
def fetch_webpage_content(url: str) -> str:
    """
    Fetches and extracts the main text content from a specific URL (like a GitHub issue, StackOverflow
    thread, or documentation page) to assist with deeper code debugging.
    """
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        for element in soup(["script", "style", "nav", "header", "footer"]):
            element.decompose()

        text = soup.get_text(separator="\n")
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase for line in lines for phrase in line.split("  "))
        clean_text = "\n".join(chunk for chunk in chunks if chunk)

        return clean_text[:8000] if len(clean_text) > 8000 else clean_text
    except Exception as e:
        return f"Failed to retrieve page content from {url}: {str(e)}"


@tool
def refresh_android_webpage(url: str):
    """
    Refreshes the web page on the android device. Use this after you started the server.
    Args:
        url: its typically like this: http://192.168.1.6:5000
    """
    os.system(f'adb shell am start -n com.android.chrome/com.google.android.apps.chrome.Main -d "{url}"')

@tool
def read_flask_logs(lines: int = 100) -> str:
    """
    Read recent Flask server logs.

    Use this to investigate flask messages, android device response and etc

    Args:
        lines: Number of recent log lines to return. Maximum 500.
    """

    try:
        log_file = Path("logs/flask_server.log")

        if not log_file.exists():
            return "Flask log file does not exist. Has the server started?"

        lines = max(1, min(lines, 500))

        with log_file.open("r", encoding="utf-8", errors="replace") as f:
            recent_logs = f.readlines()[-lines:]

        if not recent_logs:
            return "Flask log file is empty."

        return "".join(recent_logs)

    except Exception as e:
        return f"Failed to read Flask logs: {str(e)}"

@tool
def execute_adb_command(command: str) -> str:
    """Execute an Android Debug Bridge (ADB) command.
    Pass the subcommand string without the leading 'adb' prefix."""
    try:
        args = ["adb"] + command.strip().split()
        result = subprocess.run(
            args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30
        )
        if result.returncode == 0:
            return result.stdout if result.stdout.strip() else "Success."
        return f"Error: {result.stderr}"
    except Exception as e:
        return f"Exception: {str(e)}"


@tool
def capture_android_screenshot() -> bytes:
    """Describes a live screenshot of the connected Android device via ADB.

    Returns a description of what the screenshot shows. Use this whenever
    you need to visually inspect what is currently on the device screen.
    """
    MODEL = "satgeze/qwen36-35b-uncensored-1m:latest"
    PROMPT = "Describe everything visible on this Android screen."
    result = subprocess.run(
        ["adb", "exec-out", "screencap", "-p"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    image_bytes = result.stdout
    response = ollama.chat(
        model=MODEL,
        messages=[
            {
                "role": "user",
                "content": PROMPT,
                "images": [image_bytes]
            }
        ]
    )
    return response.message.content

@tool
def deploy_flask_app(
    html_content: Optional[str] = None,
    js_content: Optional[str] = None,
) -> str:
    """
    Update the web app files and (re)start the Flask server so changes go live.
    Stops the server first if it is already running, writes the new files,
    then starts the server again. Call this once per change; do not stop or
    start the server separately.

    Args:
        html_content: Complete HTML document for templates/index.html.
                      Omit to leave the existing file unchanged.
        js_content: Complete JavaScript for static/js/app.js.
                    Omit to leave the existing file unchanged.
    """
    global flask_process
    report = []

    # 1. Stop the running server
    report.append(
        "Stopped running server." if _stop_server() else "No server was running."
    )

    # 2. Write files
    try:
        if html_content is not None:
            html_file = Path("templates") / "index.html"
            html_file.parent.mkdir(parents=True, exist_ok=True)
            html_file.write_text(html_content, encoding="utf-8")
            report.append(f"Wrote {html_file} ({html_file.stat().st_size} bytes).")

        if js_content is not None:
            js_file = Path("static") / "js" / "app.js"
            js_file.parent.mkdir(parents=True, exist_ok=True)
            js_file.write_text(js_content, encoding="utf-8")
            report.append(f"Wrote {js_file} ({js_file.stat().st_size} bytes).")
    except Exception as e:
        return "\n".join(report) + f"\nFailed to write files: {e}. Server NOT restarted."

    # 3. Start the server
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["FLASK_APP"] = "app.py"
    env["PYTHONUNBUFFERED"] = "1"

    with open(LOG_FILE, "a", encoding="utf-8") as log_handle:
        flask_process = subprocess.Popen(
            ["flask", "run", "--host=0.0.0.0", f"--port={PORT}"],
            env=env,
            stdout=log_handle,   # child keeps its own copy of the fd
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

    # 4. Confirm it actually came up
    if _wait_for_port(PORT):
        report.append(
            f"Flask server started (PID {flask_process.pid}) at "
            f"http://{_get_local_ip()}:{PORT}"
        )
    else:
        report.append(
            "Server failed to start or did not respond within 10s. "
            f"Last log lines:\n{_tail_log()}"
        )

    return "\n".join(report)

# ============================================================
# 9. REGISTER AGENT TOOLS
# ============================================================

def get_tools():
    agent_runtime_tools = [
        search_internet,
        fetch_webpage_content,
        refresh_android_webpage,
        read_flask_logs,
        execute_adb_command,
        capture_android_screenshot,
        deploy_flask_app
    ]
    return agent_runtime_tools