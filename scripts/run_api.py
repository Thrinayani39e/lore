#!/usr/bin/env python
"""CLI entrypoint: python scripts/run_api.py — serves the API + dashboard."""
from __future__ import annotations

import sys

sys.path.insert(0, "src")

import uvicorn

from lore.config import settings

if __name__ == "__main__":
    uvicorn.run("lore.api.main:app", host="0.0.0.0", port=settings.api_port, reload=True)
