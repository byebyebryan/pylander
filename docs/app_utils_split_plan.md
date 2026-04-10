# app/ and utils/ Split Plan

## Context

Target ownership zones:
- **game/**: engine + minimal play/debug entry surface
- **bot_framework/**: bots, scenarios, eval, benchmark/bot orchestration
- **tooling/**: trace, plot, tracebundle, traceviewer, generic reporting/debug infra

This document is the Phase 1 artifact: a committed, file-by-file classification with a phased move checklist for later execution.

---

## Classification

### `app/` files

| File | Classification | Reason |
|------|--------------|--------|
| `__init__.py` | **bot_framework** | Re-exports CLI parser helpers used exclusively by `main.py` bench entrypoint |
| `bench.py` | **bot_framework** | Benchmark workflow orchestrator; commands run `main.py bench` which exercises bot eval |
| `benchmark_analyze.py` | **bot_framework** | Analyzes tracepack records; uses `game.core.selector_codec`, `bot_framework.botmetrics` |
| `benchmark_cache.py` | **bot_framework** | Cache key logic tied to benchmark artifacts; uses `utils.tracebundle` |
| `benchmark_compare.py` | **bot_framework** | Full compare logic for benchmark runs; uses `game.core.eval`, `bot_framework.botmetrics` |
| `benchmark_context.py` | **bot_framework** | Inspect/baseline logic for benchmark workflow; hardcodes `app/` and `utils/` files as "benchmark_tooling" |
| `benchmark_promote.py` | **bot_framework** | Promotes dirty caches; operates on benchmark artifacts |
| `benchmark_seed.py` | **bot_framework** | Seeds cache via temp git worktree for benchmark baseline |
| `bench.py` | **bot_framework** | Entry point for benchmark subcommand hierarchy |
| `cli.py` | **bridge** | Wires `main.py` CLI (play/run/sim/plot/bench) to game and bot imports; touches game+bot+app; serves both play and bench |
| `_level_resolve.py` | **game** | Resolves level/scenario bindings for runtime; imports from `game.levels` and `bot_framework.scenarios` but only for level loading |
| `config.py` | **bot_framework** | Dataclasses for Run/Bench settings; `LEVEL_DEFAULT_BOTS` maps level→bot |
| `output_viewer.py` | **tooling** | HTTP server for serving `outputs/`; pure infra, no game/bot logic |
| `plot_pack.py` | **tooling** | Builds HTML plot packs from tracepack JSON; uses `utils.tracebundle`, `utils.traceviewer` |
| `reporting.py` | **tooling** | Prints headless/batch results to terminal; generic reporting, no bot/game logic |
| `run_batch.py` | **bot_framework** | Executes batch benchmarks via `ProcessPoolExecutor`; uses `game.core.eval`, `bot_framework.scenarios` |
| `run_cached_benchmark.py` | **bot_framework** | Cached benchmark orchestration with baseline compare |
| `run_single.py` | **bridge** | Single headless run; creates `LanderGame` (game) and bot; wires game+bot+app config |
| `selector.py` | **bot_framework** | Selector parsing for bench/eval; uses `bot_framework.scenarios`, `game.levels.registry` |
| `selector_pack.py` | **bot_framework** | Resolves selector packs for benchmark modes; uses `bot_framework.scenarios` |
| `serve_outputs.py` | **tooling** | HTTP server for `outputs/`; thin wrapper around `output_viewer` |
| `trace_bundle.py` | **tooling** | Renders HTML report bundles from tracepack+compare+intent+analysis JSONs |

### `utils/` files

| File | Classification | Reason |
|------|--------------|--------|
| `__init__.py` | **tooling** | Empty |
| `plot.py` | **tooling** | Headless trajectory plotting; uses `bot_framework.bots.common_ballistics`, `game.core.components` (physics constants only); pure plotting math |
| `tracebundle.py` | **tooling** | Path/URL helpers for trace artifacts; no game/bot logic |
| `tracepack.py` | **tooling** | Tracepack serialization; uses `game.core.eval` aggregate schema |
| `traceviewer.py` | **tooling** | Renders per-run HTML detail with Plotly; no game/bot logic |

---

## Summary by Target

### Move to `bot_framework/`

```
app/__init__.py
app/bench.py
app/benchmark_analyze.py
app/benchmark_cache.py
app/benchmark_compare.py
app/benchmark_context.py
app/benchmark_promote.py
app/benchmark_seed.py
app/config.py
app/run_batch.py
app/run_cached_benchmark.py
app/selector.py
app/selector_pack.py
```

### Move to `tooling/`

```
app/output_viewer.py
app/plot_pack.py
app/reporting.py
app/serve_outputs.py
app/trace_bundle.py
utils/__init__.py
utils/plot.py
utils/tracebundle.py
utils/tracepack.py
utils/traceviewer.py
```

### Move to `game/`

```
app/_level_resolve.py
```

### Keep in `app/` as bridge (or merge into `main.py`)

```
app/cli.py        # bridge: wires play/run/sim/plot/bench; keep or fold into main.py
app/run_single.py # bridge: single run; wires game+bot+app config
```

---

## Phase 2: Move Checklist

Execute in order. Each step is a separate commit.

### Step 1 — Create `tooling/` package

```bash
mkdir -p tooling
touch tooling/__init__.py
git add tooling/__init__.py
git commit -m "chore: create tooling package skeleton"
```

### Step 2 — Move tooling-owned `utils/` files

```bash
git mv utils/tracebundle.py tooling/
git mv utils/traceviewer.py tooling/
git mv utils/tracepack.py tooling/
git mv utils/plot.py tooling/
# utils/__init__.py is already empty; leave or remove
git commit -m "refactor: move utils/ to tooling/ (tracebundle, traceviewer, tracepack, plot)"
```

### Step 3 — Move tooling-owned `app/` files

```bash
git mv app/output_viewer.py tooling/
git mv app/plot_pack.py tooling/
git mv app/reporting.py tooling/
git mv app/serve_outputs.py tooling/
git mv app/trace_bundle.py tooling/
git commit -m "refactor: move app output/plot/reporting/serve/trace_bundle to tooling/"
```

### Step 4 — Move bot_framework-owned `utils/` files to `bot_framework/`

```bash
# utils/__init__.py is empty — drop or keep as placeholder
git commit -m "refactor: drop empty utils/ package"
```

### Step 5 — Move bot_framework-owned `app/` files

```bash
git mv app/__init__.py bot_framework/
git mv app/bench.py bot_framework/
git mv app/benchmark_analyze.py bot_framework/
git mv app/benchmark_cache.py bot_framework/
git mv app/benchmark_compare.py bot_framework/
git mv app/benchmark_context.py bot_framework/
git mv app/benchmark_promote.py bot_framework/
git mv app/benchmark_seed.py bot_framework/
git mv app/config.py bot_framework/
git mv app/run_batch.py bot_framework/
git mv app/run_cached_benchmark.py bot_framework/
git mv app/selector.py bot_framework/
git mv app/selector_pack.py bot_framework/
git commit -m "refactor: move benchmark tooling from app/ to bot_framework/"
```

### Step 6 — Move bridge files to `game/` or `main.py`

```bash
# _level_resolve.py → game/
git mv app/_level_resolve.py game/
git commit -m "refactor: move _level_resolve to game/"

# cli.py — fold into main.py (bridge) or keep in app/ if main.py is the only consumer
# run_single.py — fold into game/runtime or keep in app/
```

### Step 7 — Fix imports

After each move step, run:
```bash
uv run ruff check .
uv run pytest
```

Fix any import errors before proceeding to the next step.

---

## Notes

- `app/cli.py` and `app/run_single.py` are **bridge** files: they tie game runtime to bot config. Consider folding their logic into `main.py` or `game/runtime/` in a later phase.
- `benchmark_context.py` hardcodes `app/` and `utils/` paths as "benchmark_tooling" — update that set after moving files in Phase 2.
- `trace_bundle.py` is the largest file (~1200 lines); it imports from both `app/` (benchmark modules) and `utils/` (trace helpers) — it belongs in `tooling/` since it renders HTML reports, not runs evals.
- `utils/plot.py` uses `bot_framework.bots.common_ballistics` and `game.core.components` for physics constants — these are generic ballistics math, not game engine internals, so it stays in tooling.
