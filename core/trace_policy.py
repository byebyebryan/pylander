from __future__ import annotations

TRACE_DETAIL_REPORT = "report"
TRACE_DETAIL_REPLAY = "replay"
TRACE_DETAIL_DEBUG = "debug"
TRACE_DETAIL_MODES: tuple[str, ...] = (
    TRACE_DETAIL_REPORT,
    TRACE_DETAIL_REPLAY,
    TRACE_DETAIL_DEBUG,
)


def normalize_trace_detail(value: str | None, *, default: str = TRACE_DETAIL_REPORT) -> str:
    token = str(default if value is None else value).strip().lower()
    if token not in TRACE_DETAIL_MODES:
        return str(default)
    return token
