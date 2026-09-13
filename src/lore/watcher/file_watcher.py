"""Watches a local working copy of a repo for file saves and triggers
ambient relevance checks against the indexed history.

This is the "silent teammate" surface: it runs continuously, independent
of any single agent invocation, and only speaks up (via flagger) when
something in history is genuinely relevant to the current edit.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from lore.watcher.flagger import evaluate_and_flag

logger = logging.getLogger("lore.watcher")

IGNORED_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}
WATCHED_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".java", ".rb", ".rs", ".c", ".cpp", ".h"}

# Debounce so rapid saves (autosave, formatters) don't fire a flag per keystroke.
DEBOUNCE_SECONDS = 3.0


class _Handler(FileSystemEventHandler):
    def __init__(self, repo: str, root: Path):
        self.repo = repo
        self.root = root
        self._last_seen: dict[str, float] = {}

    def on_modified(self, event):
        self._handle(event)

    def on_created(self, event):
        self._handle(event)

    def on_moved(self, event):
        # Editors that save via write-to-temp + rename emit a "moved" event
        # for the final path rather than "modified" — treat the destination
        # like a fresh edit.
        dest = getattr(event, "dest_path", None)
        if dest:
            self._handle_path(Path(dest), event.is_directory)

    def _handle(self, event):
        if event.is_directory:
            return
        self._handle_path(Path(event.src_path), False)

    def _handle_path(self, path: Path, is_directory: bool):
        if is_directory:
            return
        if any(part in IGNORED_DIRS for part in path.parts):
            return
        if path.suffix not in WATCHED_SUFFIXES:
            return

        now = time.time()
        last = self._last_seen.get(str(path), 0)
        self._last_seen[str(path)] = now
        if now - last < DEBOUNCE_SECONDS:
            return

        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return

        rel_path = str(path.relative_to(self.root))
        logger.info("checking %s against history", rel_path)
        try:
            evaluate_and_flag(self.repo, rel_path, content)
        except Exception:
            logger.exception("relevance check failed for %s", rel_path)


def watch(repo: str, path: str) -> None:
    root = Path(path).resolve()
    handler = _Handler(repo=repo, root=root)
    observer = Observer()
    observer.schedule(handler, str(root), recursive=True)
    observer.start()
    logger.info("watching %s for repo %s", root, repo)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
