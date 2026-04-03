# Pylander

A retro-modern Lunar Lander-inspired game with deterministic simulation, procedural terrain, and bot-driven play.

## Docs

- Start here: [`docs/README.md`](docs/README.md)
- Bot framework + API: [`docs/overview.md`](docs/overview.md)
- Bot docs: [`docs/plunge.md`](docs/plunge.md), [`docs/pdg.md`](docs/pdg.md)
- Scenario docs: [`docs/terminal.md`](docs/terminal.md), [`docs/boost.md`](docs/boost.md), [`docs/terrain_avoidance.md`](docs/terrain_avoidance.md)

## Features

- Procedural terrain generation (simplex)
- Physics-based lander with fuel and overdrive
- Credits, landing targets, and refueling loop
- Headless deterministic evaluation + benchmark reports
- Unified optimizer bot (`pdg`) for full-envelope flight
- Terminal benchmark bot (`plunge`)

## Default Vehicle Profile

The stock lander is tuned around a `19.5 t` fully loaded vehicle:

- dry mass `7200 kg`
- tank capacity `140` fuel units at `45 kg/unit` (`6300 kg` full-fuel mass)
- max cargo `6000 kg`
- nominal thrust `240 kN`
- overdrive ceiling `1.6x` nominal thrust with burn multiplier `8.0`

This keeps fuel and cargo near `1:1` by mass, preserves full-load thrust
margin, and makes long flat boost transfers range-feasible without making
overdrive cheap.

## Setup

```bash
uv sync
```

## Testing

```bash
uv run pytest
```

Pytest now runs in parallel by default via `xdist`. Use `uv run pytest -n 0`
when you want a serial run for debugging.

## Command model

```bash
uv run python main.py <command> [options]
```

Commands:

- `play`: single rendered interactive run
- `run`: single run (`--interactive` kept as a compatibility path, headless otherwise)
- `sim`: single headless simulation run
- `plot`: headless simulation with plotting enabled by default
- `bench`: multi-run benchmark batch

Run `uv run python main.py --help` for full help.

## Running

### Interactive (`play`)

```bash
uv run python main.py play
uv run python main.py play flat --bot pdg
```

Legacy compatibility path:

```bash
uv run python main.py run --interactive
uv run python main.py run --interactive flat --bot pdg
```

### Single headless run (`sim`)

```bash
uv run python main.py sim terminal:normal:mid:0 --bot pdg
uv run python main.py sim boost:downhill:mid:half:boost_cutoff:0 --bot pdg
uv run python main.py sim terminal:error:mid:wide:3 --bot pdg
uv run python main.py sim boost:climb:mid:half:0 --bot pdg
uv run python main.py sim plunge:mid:half:0 --bot plunge
```

Selector format:

- play/run/sim/plot selector: `level[:layer[:...]][:goal[:seed]]`
- bench selector: `level[:layer[:...]][:goal[:seed_spec]]`
- Omitted selector layers always resolve through defaults.
- Use `*` to expand exactly one selector layer in `bench` and selector-pack tooling.
- `sim` / `run` / `plot` reject `*`; use a concrete selector there.
- Use `level:seed` when setting a seed without any explicit selector layers.
- Omit goal to default to `landing`.
- Canonical examples: `boost:flat:near:half`, `terminal:error:mid:wide`, `plunge:high:full`.
- Experimental terrain examples: `terrain:reactive:terminal_backstop`, `terrain:reactive:terminal_clip`, `terrain:reactive:boost_clearance`.
- Use eval goal `boost_cutoff` under the `boost` selector root for early-stop boost checks.
- Bot selector remains bot-only: `--bot <name>`.

### Plot run (`plot`)

```bash
uv run python main.py plot boost:flat:far:half:0 --bot pdg
uv run python main.py plot boost:flat:far:half:0 --bot pdg --trace-sample-period-s 0.10
uv run python main.py plot terrain:reactive:terminal_backstop:0 --bot pdg
```

Single-run trace capture writes a trace JSON plus a small preview PNG under
`outputs/traces/<selector>/...`. The `plot` command no longer emits split or
combined PNG galleries; it enables structured trace capture for a single run.

### Benchmark batch (`bench`)

```bash
# Terminal-error subset over seed range
uv run python main.py bench \
  terminal:error:shallow:tight:0-19 \
  terminal:error:mid:wide:0-19 \
  terminal:error:steep:wide:0-19 \
  --bot pdg

# Mixed explicit + wildcard benchmark
uv run python main.py bench \
  plunge:* \
  terminal:normal:* \
  terminal:error:*:* \
  boost:flat:*:* \
  boost:downhill:*:* \
  boost:climb:*:* \
  --bot pdg \
  --json auto
```

Bench selector format:

- `level[:layer[:...]][:goal[:seed_spec]]`
- `seed_spec` supports comma/range syntax, e.g. `0-9`, `0,2,4`, `3-1`.
- Omit goal to default to `landing`.
- Omitted layers use defaults; wildcard expansion is explicit via `*`.
- If seed spec is omitted, deterministic scenarios run with seed `0`.
- If seed spec is omitted and the selector resolves to a randomized scenario, seeds auto-expand to `0-9`.

Benchmark pack tooling (`uv run python -m app.bench ...`) now reads
level metadata from `benchmark_profile()`:

- scenario sets: `smoke`, `quick`, `full`
- policy: `normal`, `observe_only`, `excluded`

Default policy profile:

- `flat`, `mountains`: `excluded`
- `terrain`: `observe_only`
- `plunge`, `terminal`, `boost`: `normal`

Repo shorthand:

- `terminal` means the public terminal selector root (`terminal:normal:*` + `terminal:error:*:*`)
- `plunge` is a separate plunge benchmark level

Focused benchmark-pack selectors also accept explicit group aliases:

- `@terminal` / `@terminal_flight` -> `terminal`
- `@plunge` -> `plunge`
- `@terminal_plunge` -> `terminal`, `plunge`

Example:

```bash
uv run python -m app.bench bundle \
  --mode focused \
  --selectors @terminal \
  --seed-spec 0-9 \
  --baseline-ref auto \
  --missing-baseline seed \
  --goal-summary "Validate current terminal changes"
```

For remote dev, you can also generate a static HTML bundle that wraps the
benchmark tracepack and interactive run-detail pages:

```bash
# Serve outputs/ once per tmux session
uv run python -m app.bench serve --port 8765

# Generate the latest static bundle with context and analysis
uv run python -m app.bench bundle \
  --mode full \
  --baseline-ref auto \
  --missing-baseline seed \
  --viewer-base-url http://myhost:8765
```

Static bundles are written under `outputs/viewer/bundles/<bundle-id>/`, and the
stable latest page is `outputs/viewer/latest/index.html`. That file is rewritten
as a full report page on each bundle generation, so refreshing the same URL
always loads the newest bundle. With the example server above, the browser URL
is `http://myhost:8765/viewer/latest/index.html`.

`app.bench bundle` can also manage the server for you. By default it checks
whether the outputs server is already running on port `8765`, starts it in the
background if needed, and prints the latest report URL. If `--viewer-base-url`
is omitted, it prefers the machine's `.lan` hostname when available (for
example `http://starship.lan:8765/viewer/latest/index.html`).

Bundle tables use pre-rendered preview PNGs for responsiveness, while run detail
pages render interactive Plotly charts directly from per-run trace JSON. The
detail pages load Plotly from a pinned CDN URL rather than a vendored local
asset.

The benchmark workflow is now phase-based under one CLI:

- `inspect`: gather repo facts, baseline candidates, and cache paths
- `run`: execute or reuse artifacts from explicit args or an existing intent
- `analyze`: write a structured outcome sidecar from benchmark artifacts
- `report`: render HTML from candidate, compare, intent, and analysis artifacts
- `bundle`: run the default inspect -> run -> analyze -> report path
- `promote`: copy a validated dirty benchmark cache onto a clean commit key after commit

When `--baseline-ref auto` or an explicit baseline resolves to a commit whose
cache is missing locally, use `--missing-baseline seed` to seed that baseline
from a detached temporary worktree and continue the compare. The default policy
is `skip` for auto baselines, which keeps the run moving but renders a
candidate-only report, and `error` for explicit baselines so requested compares
do not silently disappear.
This assumes the primary benchmark outputs remain comparable across the two
commits; if older runtime, config, or metric-shape changes alter what the pack
means, the seeded compare may still be mechanically valid but analytically weak.

## Key options

### `play` / `run` / `sim` / `plot`

- selector: `level[:layer[:...]][:goal[:seed]]`
- `-b, --bot NAME`
- `--bot-config PATH` (JSON override config for supported bots)
- `-l, --lander NAME`
- `-n, --steps N`
- `-t, --time S`
- `-f, --freq N` (headless print cadence)
- `--trace, --no-trace` (`run` / `sim`; default off)
- `--trace-sample-period-s S` (default: 0.25 when tracing is enabled)
- `--stop-on-crash`
- `--stop-on-out-of-fuel`
- `--stop-on-first-land`
- `-i, --interactive` (`run` only; compatibility alias for `play`)

`plot` is now the trace-first single-run variant of `sim`; it defaults to
`--trace`.

### `bench`

- selectors: `level[:layer[:...]][:goal[:seed_spec]]` (one or more)
- `-b, --bot NAME`
- `--bot-config PATH` (JSON override config for supported bots)
- `-l, --lander NAME`
- `-n, --steps N`
- `-t, --time S`
- `--trace-sample-period-s S` (default: 0.25)
- `--trace-detail report|replay|debug` (default: `report` for `bench`)
- `-j, --json PATH|auto`
- `--bot-profile, --no-bot-profile` (default: on)
- `--bot-profile-interval-s S` (optional profiler log interval)
- `--bot-profile-logs, --no-bot-profile-logs` (default: off)
- If worker processes are unavailable, `bench` now errors instead of silently
  falling back. Benchmark runs use the default parallel worker policy.

Benchmark records include bot compute timing metrics (avg plus p90/p99 for
passive, update, and total ms/tick) when profiling is enabled.

Benchmark JSON output is now a canonical tracepack manifest (`*.tracepack.json`)
with top-level `summary` and `records` plus per-run trace JSON files and preview
PNGs under the sibling tracepack directory. Plain `bench` runs write it by
default; explicit `--json` paths overwrite exactly, while `--json auto` uses
collision-safe names.

Trace detail defaults now vary by command:

- `bench`: `report` (optimized for report rendering and analysis)
- `plot`: `debug` (keeps verbose bot-action debug logs)
- `run` / `sim` with `--trace`: `report`

Opt into richer trace capture with `--trace-detail replay` or
`--trace-detail debug`. The default `report` mode keeps snapshots, events,
derived plot data, and final results, but omits the large per-tick control log.

Boost-phase evaluation metrics are reported through generic fields such as
`boost_cutoff_*` and `boost_goal_*`. For `terminal:normal:*` and `terminal:error:*:*`,
`boost_cutoff_*` is a spawn-time coast-entry snapshot rather than a post-burn
boost-cutoff latch. Bot-owned diagnostics stay namespaced under
`bot_<botname>_*`, for example `bot_pdg_terminal_entry_projected_dx`,
`bot_pdg_terminal_gate_mode`, and `bot_pdg_shape_curve_rmse`.

Trace-enabled runs emit trace metadata such as `trace_path`,
`trace_preview_path`, optional outputs-relative `trace_rel_path` and
`trace_preview_rel_path`, `run_key`, `run_instance_id`, `trace_detail`,
`trace_sample_period_s`, and trace event/snapshot counts.

## Project skills

Local project skills now stay intentionally small:

- `pylander-benchmark`: one benchmark workflow skill covering context inspection, baseline resolution, cache-aware benchmark reuse/compare, analysis, report rendering, the bundled default workflow, direct outputs serving, and dirty-cache promotion after commit.
- `pylander-commit-manager`: prompt-only commit playbook for goal-scoped staging and standardized commit messages.

Benchmark implementation lives in reusable app modules, not skill-local logic:
`app.selector_pack`, `app.benchmark_context`, `app.run_cached_benchmark`,
`app.benchmark_analyze`, `app.trace_bundle`, `app.output_viewer`,
`app.serve_outputs`, `app.benchmark_promote`, and `app.bench`.

Benchmark skill entrypoints:

- `uv run python -m app.bench selectors --mode quick`
- `uv run python -m app.bench inspect --mode quick --baseline-ref auto --output-json auto`
- `uv run python -m app.bench run --mode quick --baseline-ref auto --missing-baseline seed`
- `uv run python -m app.bench analyze --candidate-json outputs/benchmarks/<ref>/<stem>.tracepack.json`
- `uv run python -m app.bench report --candidate-json outputs/benchmarks/<ref>/<stem>.tracepack.json --compare-json outputs/benchmarks/<ref>/<stem>.compare_vs_<base>.json`
- `uv run python -m app.bench report --candidate-json outputs/benchmarks/<new-ref>/<new-stem>.tracepack.json --compare-json outputs/benchmarks/<new-ref>/<new-stem>.compare_vs_<base>.json --baseline-json outputs/benchmarks/<old-ref>/<old-stem>.tracepack.json`
- compare renders fall back to shared runs only when the two tracepacks cover different selector/seed sets, so full-vs-partial reports stay on the actual intersection
- `uv run python -m app.bench bundle --mode quick --baseline-ref auto --missing-baseline seed`
- `uv run python -m app.bench serve --port 8765`
- `uv run python -m app.bench promote --candidate-json outputs/benchmarks/<dirty>/<stem>.tracepack.json --target-ref HEAD`

Focused plot-pack generation remains available as an app utility rather than a
separate skill:

- `uv run python -m app.plot_pack --help`

## Bot profiling

The game loop now supports lightweight bot-loop profiling in headless mode:

```bash
PYLANDER_BOT_PROFILE=1 uv run python main.py sim terminal:normal:mid:0 --bot pdg
```

Optional interval override (seconds):

```bash
  PYLANDER_BOT_PROFILE=1 PYLANDER_BOT_PROFILE_INTERVAL_S=2 \
  uv run python main.py sim plunge:mid:half:0 --bot plunge
```

Profiled timing covers passive pre-update work, bot update time, and total
bot-loop time.

For `bench`, profiling is enabled by default with periodic profile logs disabled.

Headless `sim` output now uses:

- compact per-tick lines: `t=... | ship x=... y=... | bot=... mode=... phase=...`
- sectioned final results with generic run/boost fields first and bot-owned
  diagnostics grouped under `Bot Telemetry: <bot>`

See [`docs/overview.md`](docs/overview.md) for the bot API and profiling details.

## Controls (interactive)

- `W`/`UP`: Increase thrust
- `S`/`DOWN`: Decrease thrust
- `A`/`LEFT`: Rotate left
- `D`/`RIGHT`: Rotate right
- `I`/`J`/`K`/`L`: Pan camera
- `=`/`PageUp`, `-`/`PageDown`: Zoom camera
- `F`: Refuel (when landed)
- `TAB`: Switch actor
- `T`: Toggle ballistic path
- `R`: Reset
- `Q`/`ESC`: Quit
