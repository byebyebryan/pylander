from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence

import app.benchmark_analyze as benchmark_analyze
import app.benchmark_context as benchmark_context
import app.benchmark_promote as benchmark_promote
import app.run_cached_benchmark as run_cached_benchmark
import app.selector_pack as selector_pack
import tooling.serve_outputs as serve_outputs
import tooling.trace_bundle as trace_bundle

_COMMANDS: dict[str, tuple[str, Callable[[Sequence[str] | None], None]]] = {
    "selectors": (
        "Preview the resolved selector pack and benchmark command",
        selector_pack.main,
    ),
    "inspect": (
        "Inspect benchmark context, baseline candidates, and cache state",
        benchmark_context.main,
    ),
    "run": (
        "Run or reuse a cached benchmark pack with optional baseline compare",
        run_cached_benchmark.main,
    ),
    "analyze": (
        "Analyze benchmark artifacts and write a structured outcome sidecar",
        benchmark_analyze.main,
    ),
    "report": (
        "Render a static HTML bundle from existing benchmark artifacts",
        trace_bundle.report_main,
    ),
    "serve": (
        "Serve the local outputs directory over HTTP",
        serve_outputs.main,
    ),
    "bundle": (
        "Run the full inspect, run, analyze, and report benchmark workflow",
        trace_bundle.main,
    ),
    "promote": (
        "Promote a dirty benchmark cache into a clean commit cache key",
        benchmark_promote.main,
    ),
}


def build_parser() -> argparse.ArgumentParser:
    command_list = ", ".join(_COMMANDS)
    ap = argparse.ArgumentParser(
        description="Pylander benchmark workflow CLI",
        epilog=(
            "Commands:\n"
            "  selectors  Preview resolved selectors and the underlying main.py bench command\n"
            "  inspect    Gather repo facts, baseline candidates, and cache paths\n"
            "  run        Reuse or run a benchmark pack, with optional baseline compare\n"
            "  analyze    Write a structured analysis sidecar from benchmark artifacts\n"
            "  report     Render HTML from candidate, compare, intent, and analysis artifacts\n"
            "  serve      Serve outputs/ over HTTP\n"
            "  bundle     Run the full inspect, run, analyze, and report workflow\n"
            "  promote    Promote a dirty cache into a clean commit key after commit\n\n"
            "Use `uv run python -m app.bench <command> --help` for command-specific options."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("command", nargs="?", help=f"Benchmark command ({command_list})")
    ap.add_argument("args", nargs=argparse.REMAINDER, help=argparse.SUPPRESS)
    return ap


def main(argv: Sequence[str] | None = None) -> None:
    args = list(argv) if argv is not None else None
    parsed = build_parser().parse_args(args)
    command = str(parsed.command or "").strip().lower()

    if not command:
        print(build_parser().format_help(), end="")
        return

    if command == "help":
        if not parsed.args:
            print(build_parser().format_help(), end="")
            return
        command = str(parsed.args[0]).strip().lower()
        parsed.args = ["--help"]

    entry = _COMMANDS.get(command)
    if entry is None:
        known = ", ".join(sorted(_COMMANDS))
        raise SystemExit(
            f"Unknown benchmark command '{command}'. Expected one of: {known}"
        )
    _, handler = entry
    handler(parsed.args)


__all__ = ["build_parser", "main"]


if __name__ == "__main__":
    main()
