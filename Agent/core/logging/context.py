"""Shared logging context helpers (trace/session IDs)."""

from __future__ import annotations

import uuid


def generate_trace_id() -> str:
    """Return a short, URL-safe trace id for correlating logs."""

    return uuid.uuid4().hex[:12]


__all__ = ["generate_trace_id"]
