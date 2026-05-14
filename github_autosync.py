"""
GitHub auto sync helper for RMX Receiver.

What it does:
- On startup: git pull --rebase to restore latest sessions/config/logs.
- While bot is running: periodically commits and pushes changed runtime files.
- Safe for secrets: .env is NOT synced by default.

Enable/disable with environment variables:
  GITHUB_AUTOSYNC=1              # default 1
  GITHUB_AUTOSYNC_INTERVAL=300   # seconds, default 300
  GITHUB_AUTOSYNC_BRANCH=main    # default current branch/main
"""

from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Iterable, Optional

LOGGER = logging.getLogger("github_autosync")
BASE_DIR = Path(__file__).resolve().parent

DEFAULT_SYNC_PATHS = [
    "config.json",
    "bot.log",
    "bot.log.1",
    "bot.log.2",
    "bot.log.3",
    "bot.log.4",
    "bot.log.5",
    "sessions",
    "backups",
]


def _enabled() -> bool:
    return os.getenv("GITHUB_AUTOSYNC", "1").strip().lower() not in {"0", "false", "no", "off"}


def _run_git(args: list[str], timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(BASE_DIR),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )


def _git_available() -> bool:
    try:
        result = subprocess.run(["git", "--version"], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
        return result.returncode == 0
    except Exception:
        return False


def _is_git_repo() -> bool:
    return (BASE_DIR / ".git").exists()


def _current_branch() -> str:
    branch = os.getenv("GITHUB_AUTOSYNC_BRANCH", "").strip()
    if branch:
        return branch
    result = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], timeout=20)
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    return "main"


def _ensure_git_identity() -> None:
    name = os.getenv("GIT_COMMIT_NAME", "RMX Auto Sync")
    email = os.getenv("GIT_COMMIT_EMAIL", "rmx-autosync@users.noreply.github.com")
    _run_git(["config", "user.name", name], timeout=20)
    _run_git(["config", "user.email", email], timeout=20)


def startup_pull() -> bool:
    """Pull latest repo state before bot starts."""
    if not _enabled():
        LOGGER.info("GitHub autosync disabled by GITHUB_AUTOSYNC")
        return False
    if not _git_available():
        LOGGER.warning("git command not found; autosync disabled")
        return False
    if not _is_git_repo():
        LOGGER.warning("%s is not a git repository; autosync disabled", BASE_DIR)
        return False

    _ensure_git_identity()
    branch = _current_branch()

    # Do not fail bot startup if pull has conflict/network issue.
    result = _run_git(["pull", "--rebase", "origin", branch], timeout=120)
    if result.returncode == 0:
        LOGGER.info("GitHub autosync startup pull ok")
        return True

    LOGGER.warning("GitHub autosync startup pull failed: %s %s", result.stdout.strip(), result.stderr.strip())
    return False


def _add_existing_paths(paths: Iterable[str]) -> None:
    for relative_path in paths:
        path = BASE_DIR / relative_path
        if path.exists():
            _run_git(["add", relative_path], timeout=60)


def sync_now(reason: str = "runtime") -> bool:
    """Commit and push runtime files if changed."""
    if not _enabled() or not _is_git_repo() or not _git_available():
        return False

    _ensure_git_identity()
    branch = _current_branch()

    # Keep branch current before pushing. Ignore failure and try commit/push anyway.
    _run_git(["pull", "--rebase", "origin", branch], timeout=120)

    sync_paths = os.getenv("GITHUB_AUTOSYNC_PATHS", "").strip()
    paths = [p.strip() for p in sync_paths.split(",") if p.strip()] or DEFAULT_SYNC_PATHS
    _add_existing_paths(paths)

    diff = _run_git(["diff", "--cached", "--quiet"], timeout=30)
    if diff.returncode == 0:
        return False

    message = f"Auto sync bot data: {reason}"
    commit = _run_git(["commit", "-m", message], timeout=120)
    if commit.returncode != 0:
        LOGGER.warning("GitHub autosync commit failed: %s %s", commit.stdout.strip(), commit.stderr.strip())
        return False

    push = _run_git(["push", "origin", branch], timeout=120)
    if push.returncode == 0:
        LOGGER.info("GitHub autosync pushed runtime data")
        return True

    LOGGER.warning("GitHub autosync push failed: %s %s", push.stdout.strip(), push.stderr.strip())
    return False


def start_background_autosync(interval: Optional[int] = None) -> Optional[threading.Thread]:
    """Start background autosync thread. Returns thread or None."""
    if not _enabled():
        return None

    try:
        seconds = int(interval or os.getenv("GITHUB_AUTOSYNC_INTERVAL", "300"))
    except ValueError:
        seconds = 300
    seconds = max(60, seconds)

    def worker() -> None:
        while True:
            time.sleep(seconds)
            try:
                sync_now("periodic")
            except Exception:
                LOGGER.exception("GitHub autosync loop failed")

    thread = threading.Thread(target=worker, daemon=True, name="github-autosync")
    thread.start()
    LOGGER.info("GitHub autosync background thread started, interval=%ss", seconds)
    return thread
