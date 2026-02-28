# Setup phase (`setup` level + `setup` bot)

`setup` is the pre-terminal approach scenario. Default control uses unified `zem_zev`; `setup` bot remains available for explicit setup->coast handoff experiments.

## Phase contract

- Start from rest, upright.
- Execute one practical setup sideburn.
- Target a good ballistic approach to center.
- Hand off when projection/speed conditions are met.

## Level setup

Defined in [`levels/setup.py`](../levels/setup.py):

- Cargo: empty (`0`)
- Terrain: flat, flush target
- Target size: `110`
- Spawn geometry: arc around target with `radius in [700, 900]`
- Base entry angles: `15deg`, `45deg`, `75deg`
- Per-run angle deviation: `[-5deg, +5deg]`
- Side (left/right) deterministic from `(seed, scenario)`
- Initial state: `angle = 0`, `vx = 0`, `vy_up = 0`

Scenarios:

- `air_shallow`
- `air_mid`
- `air_steep`

Defaults:

- Default scenario: `air_mid`
- Quick benchmark subset: `air_mid`, `air_steep`

## Bot and eval

- Setup bot implementation: [`bots/setup.py`](../bots/setup.py)
- Shared setup helpers: [`bots/_launch_setup.py`](../bots/_launch_setup.py)

`setup --eval-mode focused`:

- Unified (`zem_zev`) success gate: `zem_setup_gate_done`
- Setup-bot success gate: `setup_handoff_done`
- Eval phase labels: `zem_setup_gate` or `setup_phase`

Core setup metrics:

- `setup_handoff_*`
- `setup_distance`, `setup_fuel_consumed`, `setup_fuel_per_distance`, `setup_path_efficiency`

## Commands

- `uv run python main.py setup --headless --quick-benchmark`
- `uv run python main.py setup --headless --batch --batch-scenarios air_shallow,air_mid,air_steep`
