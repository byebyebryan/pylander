from __future__ import annotations

import re


def bot_metric_prefix(bot_name: str, *, fallback: str | None = None) -> str:
    token = re.sub(r"[^a-z0-9]+", "_", str(bot_name or "").strip().lower()).strip("_")
    if not token and fallback is not None:
        token = str(fallback).strip().lower() or "unknown"
    return f"bot_{token}_"


def bot_metric_key(bot_name: str, suffix: str, *, fallback: str | None = None) -> str:
    return f"{bot_metric_prefix(bot_name, fallback=fallback)}{suffix}"


__all__ = ["bot_metric_key", "bot_metric_prefix"]
