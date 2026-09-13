#!/usr/bin/env python
"""CLI entrypoint: python scripts/run_watcher.py owner/repo /path/to/local/checkout

Reads WATCH_REPO_PATH from .env if the path arg is omitted.
"""
from __future__ import annotations

import logging
import sys

sys.path.insert(0, "src")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

from lore.config import settings
from lore.watcher.file_watcher import watch


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/run_watcher.py owner/repo [/path/to/local/checkout]")
        raise SystemExit(1)

    repo = sys.argv[1]
    path = sys.argv[2] if len(sys.argv) > 2 else settings.watch_repo_path
    if not path:
        print("No local checkout path given and WATCH_REPO_PATH is not set in .env")
        raise SystemExit(1)

    watch(repo, path)


if __name__ == "__main__":
    main()
