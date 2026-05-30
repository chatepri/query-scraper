"""
Launch run.py as a detached subprocess so Streamlit can return immediately.

Critical Windows quirk: by default, when the Streamlit parent process exits
or the user closes the browser tab, child processes inherit the parent's
fate. We need true detachment.

Handled with creationflags on Windows, start_new_session on POSIX.
"""
from __future__ import annotations

import os
import sys
import subprocess
from pathlib import Path
from typing import Optional


def _is_windows():
    return sys.platform.startswith("win")


def launch_run(client_yaml_path, mode="preview",
               python_executable=None, project_root=None):
    """Launch a detached `python run.py <client_yaml> --mode <mode>`.

    Returns the subprocess PID. Caller does NOT wait — use run_status to track.
    """
    python = python_executable or sys.executable
    cwd = project_root or os.getcwd()

    cmd = [python, "run.py", client_yaml_path, "--mode", mode]

    kwargs = {"cwd": cwd, "stdin": subprocess.DEVNULL}

    log_dir = Path(cwd) / "data" / "subprocess_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    client_id = Path(client_yaml_path).stem
    log_path = log_dir / f"{client_id}.log"
    log_fh = open(log_path, "a", buffering=1)
    kwargs["stdout"] = log_fh
    kwargs["stderr"] = subprocess.STDOUT

    if _is_windows():
        kwargs["creationflags"] = (
            subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        )
        kwargs["close_fds"] = False
    else:
        kwargs["start_new_session"] = True

    proc = subprocess.Popen(cmd, **kwargs)
    return proc.pid


def get_log_path(client_id, project_root=None):
    cwd = project_root or os.getcwd()
    return Path(cwd) / "data" / "subprocess_logs" / f"{client_id}.log"


def tail_log(client_id, n_lines=40, project_root=None):
    log_path = get_log_path(client_id, project_root)
    if not log_path.exists():
        return "(no log yet)"
    try:
        with open(log_path) as f:
            lines = f.readlines()
        return "".join(lines[-n_lines:])
    except Exception as e:
        return f"(error reading log: {e})"