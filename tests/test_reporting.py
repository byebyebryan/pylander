from __future__ import annotations

from app.reporting import print_headless_results


def test_print_headless_results_includes_trace_metadata(capsys) -> None:
    print_headless_results(
        {
            "state": "landed",
            "success": True,
            "trace_detail": "report",
            "trace_path": "outputs/benchmarks/head/pack.traces/case_a.trace.json",
            "trace_preview_path": "outputs/benchmarks/head/pack.traces/case_a.png",
        }
    )

    output = capsys.readouterr().out
    assert "report" in output
    assert "outputs/benchmarks/head/pack.traces/case_a.trace.json" in output
    assert "outputs/benchmarks/head/pack.traces/case_a.png" in output
