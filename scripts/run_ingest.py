#!/usr/bin/env python
"""CLI entrypoint: python scripts/run_ingest.py owner/repo [max_per_kind]"""
from __future__ import annotations

import sys

sys.path.insert(0, "src")

from lore.config import settings
from lore.ingestion.indexer import ingest_repo


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/run_ingest.py owner/repo [max_per_kind]")
        raise SystemExit(1)

    repo = sys.argv[1]
    max_per_kind = int(sys.argv[2]) if len(sys.argv) > 2 else 50

    print(f"Ingesting {repo} (up to {max_per_kind} of each: commits, PRs, issues)...")
    count = ingest_repo(repo, settings.github_token, max_per_kind=max_per_kind)
    print(f"Done. Indexed {count} chunks.")


if __name__ == "__main__":
    main()
