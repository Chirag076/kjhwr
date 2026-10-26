"""
Vercel entry point.

Vercel serves this file as a Python function and `vercel.json` rewrites every
/api/* path to it, so the same FastAPI app that runs in the Docker container
also runs serverless with no second implementation to keep in step.

Serverless gets no persistent disk, so the fixtures are not available here and
the app reads Elexon live. The TTL cache still helps within a warm instance.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
os.environ.setdefault("ELEXON_OFFLINE", "0")

from windsight.api import app  # noqa: E402

# Vercel's Python runtime looks for an ASGI callable named `app`.
__all__ = ["app"]
