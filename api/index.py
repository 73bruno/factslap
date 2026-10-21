"""Vercel serverless entry point: the FactSlap v2 API (factslap/api.py)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from factslap.api import create_app  # noqa: E402

app = create_app()
