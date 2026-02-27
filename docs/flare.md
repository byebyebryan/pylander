# Flare phase (`flare` level + `flare` bot)

This phase is the terminal-approach sandbox: high-energy curved entries that must converge into a clean final descent and touchdown.

## Level setup

Defined in [`levels/flare.py`](../levels/flare.py):

- Cargo: half (`2250`)
- Terrain: flat, flush/flatten target
- Target size: `110`
- Spawn geometry: upper arc around target center, `radius in [700, 900]`
- Arc base angles from horizon: `15deg`, `30deg`, `45deg`, `60deg`, `75deg`
- Per-run angle deviation: `[-5deg, +5deg]` from the base angle
- Target entry timing: `target_flight_time_s in [10, 12]`
- Spawn side (left/right) is deterministic from `(seed, scenario)`
- Initial attitude is retrograde (opposite the spawned velocity vector)

Initial velocity solve:

- `dx = R * cos(theta_base + theta_dev)`
- `dy = R * sin(theta_base + theta_dev)`
- `vx = -dx / T`
- `vy_up = ((0.5 * g * T^2) - dy) / T`

where `R in [700,900]`, `theta_dev in [-5deg,+5deg]`, `T in [10,12]`, and `g = abs(GRAVITY)`.

## Scenarios

- `shallower` (`15deg`)
- `shallow` (`30deg`)
- `mid` (`45deg`)
- `steep` (`60deg`)
- `steeper` (`75deg`)

Defaults:

- Default scenario: `mid`
- Quick benchmark subset: `shallower`, `mid`, `steeper`

## Evaluation goals and metrics

Primary goals:

- Stable success across all entry angles
- No late panic burns, no hover stall near ground
- Reasonable fuel/time without sacrificing touchdown quality

Useful metrics (from [`core/eval.py`](../core/eval.py)):

- Outcome: `state`, `success_rate`, `landing_offset`
- Efficiency: `fuel_consumed`, `fuel_per_distance`, `path_efficiency`
- Timing: `time`, `time_to_first_land`

Common eval commands:

- `uv run python main.py flare --headless --quick-benchmark`
- `uv run python main.py flare --headless --batch --batch-scenarios shallower,shallow,mid,steep,steeper`

## Flare bot: detailed control flow

Implementation: [`bots/flare.py`](../bots/flare.py)

Every frame, `FlareBot` runs this pipeline:

1. Acquire target with radar (`pick_target`).
2. Estimate ballistic intercept with `estimate_ballistic_projection` -> `projected_dx`, `t_fall`.
3. Choose guidance phase (`sideburn`, `coupled_terminal`, `touchdown`).
4. Build setpoints (`vx_sp`, `vy_sp`) for the chosen phase.
5. Convert setpoints to accelerations (`a_x_sp`, `a_up_sp`).
6. Allocate thrust + angle with rate limits, tilt caps, and throttle caps.

If no target is visible, bot enters a conservative vertical flare/search fallback.

### Phase selection

The bot keeps one explicit sideburn state (`_sideburn_active`) plus release and cooldown timers:

- Enter `sideburn` when projected overshoot and lateral speed/offset gates pass.
- Stay in `sideburn` until exit gates pass for consecutive frames, timeout hits, altitude is too low, or climb abort trips.
- Enter `touchdown` only when low altitude and low lateral error/speed are already true.
- Otherwise run `coupled_terminal`.

This is intentionally hysteretic. Entry and exit are not symmetric, so the bot avoids phase flipping.

### Setpoint generation (`vx_sp`, `vy_sp`)

Sideburn:

- `vx_sp` is an aggressive lateral target: floor + altitude gain + tracking buffer, capped by `sideburn_vx_cap`.
- `vy_sp` is a controlled descent schedule from `sideburn_descent_*`.

Coupled terminal:

- `vx_sp` blends tracking and damping:
  - `vx_track = projected_dx / t_go`
  - `vx_stop = -vx`
  - `vx_sp = w * vx_track + (1 - w) * vx_stop`
- `vx_sp` is clipped by global/low-alt/near-target caps.
- `vy_sp` follows `coupled_descent_*`, with low-alt misalignment guard enforcing minimum sink.

Touchdown:

- Tight lateral cap near zero (`coupled_near_vx_cap`)
- Very gentle descent from `touchdown_descent_*`

### Burn timing model (vertical trigger)

The burn gate is based on estimated stopping geometry:

- `spool_time` from throttle ramp-up and current thrust level
- `spool_distance = down_speed * spool_time + burn_spool_quadratic_accel * spool_time^2`
- `flare_speed(alt)` from `burn_flare_speed_*`
- `speed_to_kill = max(0, down_speed - flare_speed)`
- `stop_distance = speed_to_kill^2 / (2 * up_acc_max)`
- `burn_margin` from `burn_margin_*` (larger when lateral error is larger)
- `burn_altitude = stop_distance + spool_distance + burn_margin`

Then burn starts when:

- `down_speed > burn_activation_down_speed_min`, and
- `alt <= burn_altitude` **or**
- `time_to_impact <= time_to_brake + burn_enter_time_margin`

`burn_hold_frames` adds hysteresis to avoid one-frame flicker.

### Controller and allocator

Horizontal acceleration:

- Sideburn and coupled phases both use projection-aware lateral control with damping.
- Coupled path uses `coupled_ax_pos_gain`, `coupled_ax_vel_gain`, `coupled_ax_damping`, `coupled_ax_cap`.

Vertical acceleration:

- `coast_hold`: thrust-backed descent with anti-hover penalty and emergency brake floor.
- `terminal_burn`: high upward command tied to available acceleration.
- `flare`/touchdown: softer proportional schedule near ground.

Thrust and angle allocation:

- Angle command from `atan2(a_x_sp, a_up_sp)` then clamped by phase-specific tilt caps and rate limits.
- Very low altitude adds tighter tilt caps.
- Thrust from requested acceleration magnitude, then clipped by engine limits and overdrive policy.
- Touchdown cut (`touchdown_zero_*`) hard zeros thrust/angle only in very low, very slow, near-center conditions.

## Why there are many numbers (and why that is useful)

The parameter count is high because this bot is a hybrid controller, not one smooth PID. It has:

- phase gates (when to switch)
- command shapers (desired velocity profiles)
- actuator constraints (what the vehicle can physically do)
- hysteresis (keep decisions stable over noisy frame-to-frame estimates)

These are useful because each group handles a different failure mode:

- Without gate thresholds: sideburn chatters on/off near boundaries.
- Without hysteresis counters/holds: burn flickers and phase switching oscillates.
- Without caps/low-alt clamps: controller asks for impossible lateral authority near ground.
- Without emergency floors: late high-speed entries run out of stopping margin.

So the "many numbers" are mostly stability and safety rails around a simple core idea.

## How the numbers fit together

Think of them as a chain, not independent knobs:

1. **Projection quality** (`projection_*`) affects `projected_dx`, `t_go`.
2. **Phase gates** (`sideburn_enter_*`, `sideburn_exit_*`, `touchdown_*`, `anti_hover_*`) decide active mode.
3. **Setpoint shapers** (`*_descent_*`, `*_vx_*`) turn mode into target velocities.
4. **Controller gains/caps** (`coupled_ax_*`, `sideburn_ax_*`) map velocity errors into accel demand.
5. **Burn trigger model** (`burn_*`) decides when vertical mode must hard-brake.
6. **Allocator limits** (`*_max_tilt`, `*_angle_rate`, throttle caps) enforce physical feasibility.
7. **Hysteresis timers** (`*_hold_frames`, `*_cooldown_frames`) stop oscillation between states.

When tuning, move adjacent links together. Example:

- If you lower `sideburn_enter_vx`, also review `sideburn_exit_vx` and `sideburn_release_frames`, or sideburn may re-enter too often.
- If you increase `coupled_ax_pos_gain`, review `coupled_ax_cap` and low-alt caps, or you may command aggressive low-alt tilt.
- If you reduce `burn_margin_base`, review `burn_enter_time_margin` and `burn_hold_frames`, or you risk late/flickery burn initiation.

## Top knobs cheat sheet

Start with these before touching the rest.

| Knob | Primary effect | Increase does | Decrease does | Watch metrics |
| --- | --- | --- | --- | --- |
| `burn_margin_base` | Burn conservatism | Earlier burn, safer, more fuel | Later burn, riskier, less fuel | crash rate, fuel |
| `burn_enter_time_margin` | Time-based burn buffer | Earlier trigger on short TTI | More reliance on altitude gate | late-burn crashes |
| `burn_hold_frames` | Burn hysteresis | Less flicker, more commitment | Snappier mode changes | thrust chatter |
| `sideburn_enter_vx` | Sideburn entry aggressiveness | Fewer sideburn entries | More sideburn entries | path efficiency, oscillation |
| `sideburn_exit_vx` | Sideburn release strictness | Sideburn holds longer | Sideburn exits earlier | time, lateral wobble |
| `sideburn_release_frames` | Exit confidence | Smoother exit, slower release | Faster exit, more chatter risk | phase toggling |
| `coupled_vx_track_weight` | Track-vs-damp blend | More position chasing | More velocity damping | landing_offset, time |
| `coupled_ax_pos_gain` | Lateral correction strength | Faster lateral convergence | Slower lateral convergence | offset, low-alt tilt |
| `coupled_low_alt_ax_cap` | Low-alt lateral authority | More low-alt correction | Gentler low-alt behavior | touchdown stability |
| `touchdown_zero_vy` | Engine cutoff tolerance | Earlier cutoff | Later cutoff | bounce/hover near ground |

Practical tuning order:

1. Burn model (`burn_*`)
2. Sideburn gates (`sideburn_enter_*`, `sideburn_exit_*`)
3. Coupled lateral gains/caps (`coupled_ax_*`)
4. Touchdown cut (`touchdown_zero_*`)

## Full parameter map (grouped)

`FlareControlConfig` is grouped by prefix:

- `sideburn_*`: sideburn phase entry/exit/direction/setpoint/caps
- `coupled_*`: terminal lateral/vertical shaping and low-alt constraints
- `burn_*`: burn start model and burn hysteresis
- `touchdown_*`: final settle and engine cutoff rules
- `projection_*`: ballistic projection fidelity
- `anti_hover_*`, `eco_glide_*`, `emergency_*`: safety and anti-stall guardrails

## Entry trajectories (docs asset)

The plot below shows engine-off center-hit trajectories for the five angle profiles.

![Flare entry ballistic trajectories](assets/flare_entry_ballistic_profiles.png)

### Regenerate the plot

```bash
uv run python - <<'PY'
from pathlib import Path
import math
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from core.config import GRAVITY
from levels import flare as flare_level

R = float(flare_level._SPAWN_RADIUS)
T = float(flare_level._TARGET_FLIGHT_TIME_S)
profiles = tuple(flare_level._ANGLE_PROFILES)
g = abs(float(GRAVITY))
out = Path("docs/assets/flare_entry_ballistic_profiles.png")
out.parent.mkdir(parents=True, exist_ok=True)

fig, ax = plt.subplots(figsize=(9.5, 5.5), dpi=160)
ax.axhline(0.0, color="#333333", linewidth=1.0, alpha=0.7)
ax.scatter([0.0], [0.0], s=28, color="#111111", label="target")

for name, angle_deg in profiles:
    th = math.radians(float(angle_deg))
    dx = R * math.cos(th)
    dy = R * math.sin(th)
    vx = -(dx / T)
    vy = ((0.5 * g * T * T) - dy) / T
    ts = [T * i / 220.0 for i in range(221)]
    xs = [dx + vx * t for t in ts]
    ys = [dy + vy * t - 0.5 * g * t * t for t in ts]
    ax.plot(xs, ys, linewidth=2.0, label=f"{name} ({int(angle_deg)}deg)")

ax.set_aspect("equal", adjustable="box")
ax.set_xlim(-40.0, R + 60.0)
ax.set_ylim(-40.0, R + 80.0)
ax.set_xlabel("x offset from target")
ax.set_ylabel("y (altitude)")
ax.set_title(f"Flare entry scenarios: engine-off center-hit ballistics (T={T:.0f}s)")
ax.grid(True, linestyle=":", alpha=0.25)
ax.legend(loc="upper right", fontsize=8)
fig.tight_layout()
fig.savefig(out)
plt.close(fig)
PY
```

