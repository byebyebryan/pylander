from __future__ import annotations

import html
import json
import shutil
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ASSETS_ROOT = (_REPO_ROOT / "skills" / "pylander-benchmark-runner" / "assets").resolve()
_PLOTLY_FILENAME = "plotly-basic-2.35.2.min.js"
_PLOTLY_VENDOR_PATH = (_ASSETS_ROOT / _PLOTLY_FILENAME).resolve()


def ensure_viewer_assets(outputs_root: Path) -> dict[str, str]:
    assets_dir = (outputs_root / "viewer" / "assets").resolve()
    assets_dir.mkdir(parents=True, exist_ok=True)
    plotly_target = (assets_dir / _PLOTLY_FILENAME).resolve()
    if not _PLOTLY_VENDOR_PATH.exists():
        raise SystemExit(f"Missing vendored Plotly asset: {_PLOTLY_VENDOR_PATH}")
    shutil.copy2(_PLOTLY_VENDOR_PATH, plotly_target)
    return {"plotly_rel": plotly_target.relative_to(outputs_root).as_posix()}


def _json_html(value: Any) -> str:
    return (
        json.dumps(value, separators=(",", ":"))
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
    )


def _format_float(value: Any, digits: int = 2) -> str:
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "-"


def _render_table(headers: list[str], rows: list[list[str]]) -> str:
    head_html = "".join(f"<th>{html.escape(item)}</th>" for item in headers)
    body_rows = []
    for row in rows:
        cols = "".join(f"<td>{cell}</td>" for cell in row)
        body_rows.append(f"<tr>{cols}</tr>")
    if not body_rows:
        body_rows.append(f"<tr><td colspan=\"{len(headers)}\">(none)</td></tr>")
    return (
        "<table>"
        f"<thead><tr>{head_html}</tr></thead>"
        f"<tbody>{''.join(body_rows)}</tbody>"
        "</table>"
    )


def _render_events_table(events: list[dict[str, Any]]) -> str:
    rows = []
    for event in events:
        if not isinstance(event, dict):
            continue
        rows.append(
            [
                html.escape(str(event.get("name") or "")),
                html.escape(str(event.get("label") or "")),
                _format_float(event.get("time_s"), 3),
                _format_float(event.get("x"), 3),
                _format_float(event.get("y"), 3),
            ]
        )
    return _render_table(["Name", "Label", "Time", "X", "Y"], rows)


def _run_metric_cards(record: dict[str, Any]) -> list[tuple[str, str]]:
    cards: list[tuple[str, str]] = [
        ("State", str(record.get("state") or "-")),
        ("Failure", str(record.get("failure_mode") or "-")),
        ("Fuel", _format_float(record.get("fuel_consumed"), 3)),
        ("Time", _format_float(record.get("time"), 3)),
    ]
    if record.get("landing_offset") is not None:
        cards.append(("Offset", _format_float(record.get("landing_offset"), 3)))
    if record.get("avg_speed") is not None:
        cards.append(("Avg Speed", _format_float(record.get("avg_speed"), 3)))
    if record.get("bot_profile_total_ms_per_tick") is not None:
        cards.append(("Bot ms/tick", _format_float(record.get("bot_profile_total_ms_per_tick"), 3)))
    return cards


def _render_metric_card_grid(cards: list[tuple[str, str]]) -> str:
    return "".join(
        "<div class=\"card\">"
        f"<div class=\"label\">{html.escape(label)}</div>"
        f"<div class=\"value\">{html.escape(value)}</div>"
        "</div>"
        for label, value in cards
    )


def render_trace_detail_html(
    *,
    title: str,
    selector: str,
    scenario_selector: str | None,
    record: dict[str, Any],
    trace_payload: dict[str, Any],
    plotly_href: str,
    top_links: list[tuple[str, str | None]],
    raw_links: list[tuple[str, str | None]],
    repro_commands: list[str],
) -> str:
    plot_payload = dict(trace_payload.get("plot") or {})
    events = list(plot_payload.get("events") or trace_payload.get("events") or [])
    trace_plot_json = _json_html(plot_payload)
    cards = _render_metric_card_grid(_run_metric_cards(record))
    top_links_html = " | ".join(
        f'<a href="{html.escape(href)}">{html.escape(label)}</a>'
        for label, href in top_links
        if href
    )
    raw_links_html = " | ".join(
        f'<a href="{html.escape(href)}">{html.escape(label)}</a>'
        for label, href in raw_links
        if href
    )
    repro_html = "".join(f"<p><code>{html.escape(cmd)}</code></p>" for cmd in repro_commands if cmd)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f4f1e8;
      --panel: #fffaf0;
      --ink: #1d1f24;
      --muted: #575f66;
      --accent: #0e6b60;
      --warn: #8e3b2e;
      --line: #d8cfbf;
      --shadow: rgba(29, 31, 36, 0.08);
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: Georgia, "Times New Roman", serif; color: var(--ink); background: linear-gradient(180deg, #f7f4ec 0%, var(--bg) 100%); }}
    main {{ max-width: 1280px; margin: 0 auto; padding: 24px 20px 48px; }}
    header, section, .card {{ background: var(--panel); border: 1px solid var(--line); border-radius: 16px; box-shadow: 0 8px 24px var(--shadow); }}
    header, section {{ padding: 18px 20px; margin-bottom: 18px; }}
    h1, h2, h3 {{ margin: 0 0 10px; font-family: "Palatino Linotype", "Book Antiqua", Palatino, serif; }}
    .meta, .links, .muted {{ color: var(--muted); }}
    .banner {{ display: inline-block; padding: 8px 12px; border-radius: 999px; font-weight: 700; background: rgba(14, 107, 96, 0.12); color: var(--accent); }}
    .banner.bad {{ background: rgba(142, 59, 46, 0.12); color: var(--warn); }}
    .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 12px; margin-top: 16px; }}
    .card {{ padding: 14px; }}
    .label {{ color: var(--muted); font-size: 0.82rem; text-transform: uppercase; letter-spacing: 0.04em; }}
    .value {{ font-size: 1.35rem; margin-top: 6px; }}
    a {{ color: var(--accent); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--line); vertical-align: top; }}
    th {{ color: var(--muted); font-size: 0.82rem; text-transform: uppercase; letter-spacing: 0.04em; }}
    .plot-stack {{ display: grid; grid-template-columns: 1fr; gap: 20px; }}
    .plot-frame {{ margin: 0; }}
    .plot-frame h3 {{ margin: 0 0 8px; font-size: 1rem; }}
    .plot-frame .chart {{ width: 100%; height: 380px; border: 1px solid var(--line); border-radius: 12px; background: #fbf8f1; }}
    code {{ font-family: "SFMono-Regular", Consolas, "Liberation Mono", monospace; font-size: 0.9rem; white-space: pre-wrap; word-break: break-word; }}
  </style>
  <script src="{html.escape(plotly_href)}"></script>
</head>
<body>
  <main>
    <header>
      <p class="links">{top_links_html}</p>
      <h1>{html.escape(selector)}</h1>
      <p class="meta">scenario={html.escape(str(scenario_selector or ""))}</p>
      <p class="banner {'bad' if not bool(record.get('success', False)) else ''}">{html.escape(str(record.get('state') or '-'))} / failure={html.escape(str(record.get('failure_mode') or '-'))}</p>
      <div class="cards">{cards}</div>
    </header>

    <section>
      <h2>Interactive Detail</h2>
      <div class="plot-stack">
        <section class="plot-frame"><h3>Trajectory</h3><div id="chart-spatial" class="chart"></div></section>
        <section class="plot-frame"><h3>Trajectory by Speed</h3><div id="chart-speed-spatial" class="chart"></div></section>
        <section class="plot-frame"><h3>Trajectory by Thrust</h3><div id="chart-thrust-spatial" class="chart"></div></section>
        <section class="plot-frame"><h3>Flight Metrics</h3><div id="chart-metrics" class="chart"></div></section>
      </div>
      <p class="links">{raw_links_html}</p>
    </section>

    <section>
      <h2>Events</h2>
      {_render_events_table(events)}
    </section>

    <section>
      <h2>Commands</h2>
      <details>
        <summary>Show repro commands</summary>
        {repro_html}
      </details>
    </section>
  </main>
  <script id="trace-plot-json" type="application/json">{trace_plot_json}</script>
  <script>
    const plotPayload = JSON.parse(document.getElementById("trace-plot-json").textContent);
    const samples = plotPayload.samples || {{}};
    const terrain = plotPayload.terrain || {{}};
    const target = plotPayload.target || {{}};
    const events = Array.isArray(plotPayload.events) ? plotPayload.events : [];
    const eventPoints = events.filter((event) => Number.isFinite(Number(event.x)) && Number.isFinite(Number(event.y)));
    const baseConfig = {{responsive: true, displaylogo: false}};
    const paperBg = "#fffaf0";
    const plotBg = "#fbf8f1";
    const xValues = Array.isArray(samples.x) ? samples.x : [];
    const yValues = Array.isArray(samples.y) ? samples.y : [];
    const timeValues = Array.isArray(samples.time_s) ? samples.time_s : [];
    const speedValues = Array.isArray(samples.speed) ? samples.speed.map((value) => Number(value)) : [];
    const thrustValues = Array.isArray(samples.thrust) ? samples.thrust.map((value) => Number(value)) : [];
    const angleValues = Array.isArray(samples.angle) ? samples.angle.map((value) => Number(value)) : [];
    const vxValues = Array.isArray(samples.vx) ? samples.vx.map((value) => Number(value)) : [];
    const vyValues = Array.isArray(samples.vy) ? samples.vy.map((value) => Number(value)) : [];
    const thrustXValues = thrustValues.map((value, index) => value * Math.sin(Number(angleValues[index] || 0)));
    const thrustYValues = thrustValues.map((value, index) => value * Math.cos(Number(angleValues[index] || 0)));

    const clamp01 = (value) => Math.max(0, Math.min(1, value));
    const hexToRgb = (hex) => {{
      const normalized = String(hex || "").replace("#", "");
      if (normalized.length !== 6) return [0, 0, 0];
      return [
        Number.parseInt(normalized.slice(0, 2), 16),
        Number.parseInt(normalized.slice(2, 4), 16),
        Number.parseInt(normalized.slice(4, 6), 16),
      ];
    }};
    const rgbToHex = (rgb) =>
      "#" + rgb.map((value) => Math.round(value).toString(16).padStart(2, "0")).join("");
    const interpolateColor = (scale, value, minValue, maxValue) => {{
      const safeMin = Number.isFinite(minValue) ? minValue : 0;
      const safeMax = Number.isFinite(maxValue) && maxValue > safeMin ? maxValue : safeMin + 1;
      const t = clamp01((Number(value) - safeMin) / (safeMax - safeMin));
      for (let index = 1; index < scale.length; index += 1) {{
        const [stopB, colorB] = scale[index];
        if (t > stopB) continue;
        const [stopA, colorA] = scale[index - 1];
        const localT = stopB <= stopA ? 0 : (t - stopA) / (stopB - stopA);
        const rgbA = hexToRgb(colorA);
        const rgbB = hexToRgb(colorB);
        return rgbToHex(rgbA.map((channel, rgbIndex) => channel + ((rgbB[rgbIndex] - channel) * localT)));
      }}
      return scale[scale.length - 1][1];
    }};
    const valueExtent = (values) => {{
      const finite = values.map((value) => Number(value)).filter((value) => Number.isFinite(value));
      if (!finite.length) return {{min: 0, max: 1}};
      const minValue = Math.min(...finite);
      const maxValue = Math.max(...finite);
      if (maxValue <= minValue) return {{min: minValue, max: minValue + 1}};
      return {{min: minValue, max: maxValue}};
    }};
    const speedColorScale = [
      [0.0, "#fff3bf"],
      [0.35, "#ffd166"],
      [0.65, "#f77f00"],
      [1.0, "#c1121f"],
    ];
    const thrustColorScale = [
      [0.0, "#d9f0ff"],
      [0.35, "#74c0fc"],
      [0.7, "#2b8aeb"],
      [1.0, "#0b3d91"],
    ];
    const buildScalarSpatialTraces = ({{values, colorscale, colorbarTitle}}) => {{
      const traces = [
        {{
          type: "scatter",
          mode: "lines",
          x: xValues,
          y: yValues,
          line: {{color: "#d6cdbd", width: 2}},
          hoverinfo: "skip",
          showlegend: false,
        }},
      ];
      const scalarExtent = valueExtent(values);
      for (let index = 1; index < Math.min(xValues.length, yValues.length, values.length); index += 1) {{
        const x0 = Number(xValues[index - 1]);
        const y0 = Number(yValues[index - 1]);
        const x1 = Number(xValues[index]);
        const y1 = Number(yValues[index]);
        const value0 = Number(values[index - 1]);
        const value1 = Number(values[index]);
        if (![x0, y0, x1, y1, value0, value1].every((value) => Number.isFinite(value))) continue;
        traces.push({{
          type: "scatter",
          mode: "lines",
          x: [x0, x1],
          y: [y0, y1],
          line: {{
            color: interpolateColor(colorscale, 0.5 * (value0 + value1), scalarExtent.min, scalarExtent.max),
            width: 4,
          }},
          hoverinfo: "skip",
          showlegend: false,
        }});
      }}
      traces.push({{
        type: "scatter",
        mode: "markers",
        x: xValues,
        y: yValues,
        marker: {{
          size: traces.length > 1 ? 0.1 : 7,
          opacity: traces.length > 1 ? 0.001 : 0.9,
          color: values,
          cmin: scalarExtent.min,
          cmax: scalarExtent.max,
          colorscale: colorscale,
          colorbar: {{
            title: colorbarTitle,
            outlinecolor: "#cfc4b2",
          }},
        }},
        hovertemplate: `${{colorbarTitle}}<br>x=%{{x:.1f}}<br>y=%{{y:.1f}}<br>value=%{{marker.color:.3f}}<extra></extra>`,
        showlegend: false,
      }});
      return traces;
    }};
    const eventStyle = (name) => {{
      switch (String(name || "").toLowerCase()) {{
        case "success":
          return {{symbol: "star", color: "#2f9e44"}};
        case "crash":
          return {{symbol: "x", color: "#c92a2a"}};
        case "out_of_fuel":
          return {{symbol: "triangle-down", color: "#b26b00"}};
        case "boost_cutoff":
          return {{symbol: "diamond", color: "#cf7b00"}};
        case "terminal_entry":
          return {{symbol: "circle", color: "#5b73c6"}};
        default:
          return {{symbol: "square", color: "#8e3b2e"}};
      }}
    }};

    const padTrace = () => {{
      if (target.x === undefined || target.y === undefined) return null;
      const size = Math.max(10, Math.abs(Number(target.size || 0)) * 0.5 || 10);
      return {{
        type: "scatter",
        mode: "lines",
        name: target.label || "target",
        x: [Number(target.x) - size, Number(target.x) + size],
        y: [Number(target.y), Number(target.y)],
        line: {{color: "#2ecc71", width: 5}},
      }};
    }};

    const terrainTrace = {{
      type: "scatter",
      mode: "lines",
      name: "terrain",
      x: terrain.xs || [],
      y: terrain.ys || [],
      line: {{color: "#6c614d", width: 2}},
    }};
    const pathTrace = {{
      type: "scatter",
      mode: "lines",
      name: "trajectory",
      x: xValues,
      y: yValues,
      line: {{color: "#0e6b60", width: 3}},
    }};
    const eventTrace = {{
      type: "scatter",
      mode: "markers",
      name: "events",
      x: eventPoints.map((event) => Number(event.x)),
      y: eventPoints.map((event) => Number(event.y)),
      customdata: eventPoints.map((event) => [event.label || event.name || "", event.time_s]),
      hovertemplate: "%{{customdata[0]}}<br>x=%{{x:.1f}}<br>y=%{{y:.1f}}<br>t=%{{customdata[1]:.2f}}s<extra></extra>",
      marker: {{
        size: eventPoints.map((event) => {{
          const eventName = String(event.name || "").toLowerCase();
          return eventName === "success" || eventName === "crash" ? 16.5 : 15;
        }}),
        color: eventPoints.map((event) => eventStyle(event.name).color),
        symbol: eventPoints.map((event) => eventStyle(event.name).symbol),
        line: {{width: 2.0, color: "#fffaf0"}},
      }},
    }};
    const ballistic = plotPayload.ballistic_curve || {{}};
    const ballisticTrace = Array.isArray(ballistic.xs) ? {{
      type: "scatter",
      mode: "lines",
      name: ballistic.source === "boost_cutoff" ? "boost cutoff ballistic" : "ballistic",
      x: ballistic.xs,
      y: ballistic.ys,
      line: {{color: "#cf7b00", width: 2, dash: "dot"}},
    }} : null;
    const reference = plotPayload.reference_curve || {{}};
    const referenceTrace = Array.isArray(reference.xs) ? {{
      type: "scatter",
      mode: "lines",
      name: "reference",
      x: reference.xs,
      y: reference.ys,
      line: {{color: "#5b73c6", width: 2, dash: "dash"}},
    }} : null;

    const layoutBase = (title, extra = {{}}) => Object.assign({{
      title,
      paper_bgcolor: paperBg,
      plot_bgcolor: plotBg,
      margin: {{l: 64, r: 24, t: 56, b: 34}},
      legend: {{
        orientation: "h",
        yanchor: "bottom",
        y: 1.02,
        xanchor: "left",
        x: 0,
        bgcolor: "rgba(255, 250, 240, 0.88)",
      }},
    }}, extra);

    Plotly.newPlot(
      "chart-spatial",
      [terrainTrace, pathTrace, padTrace(), ballisticTrace, referenceTrace, eventTrace].filter(Boolean),
      layoutBase("Trajectory", {{
        xaxis: {{title: ""}},
        yaxis: {{title: "Y", scaleanchor: "x", scaleratio: 1}},
      }}),
      baseConfig,
    );

    Plotly.newPlot(
      "chart-speed-spatial",
      [terrainTrace, ...buildScalarSpatialTraces({{values: speedValues, colorscale: speedColorScale, colorbarTitle: "speed"}}), padTrace()].filter(Boolean),
      layoutBase("Trajectory by Speed", {{
        xaxis: {{title: ""}},
        yaxis: {{title: "Y", scaleanchor: "x", scaleratio: 1}},
        showlegend: false,
      }}),
      baseConfig,
    );

    Plotly.newPlot(
      "chart-thrust-spatial",
      [terrainTrace, ...buildScalarSpatialTraces({{values: thrustValues, colorscale: thrustColorScale, colorbarTitle: "thrust"}}), padTrace()].filter(Boolean),
      layoutBase("Trajectory by Thrust", {{
        xaxis: {{title: ""}},
        yaxis: {{title: "Y", scaleanchor: "x", scaleratio: 1}},
        showlegend: false,
      }}),
      baseConfig,
    );

    Plotly.newPlot(
      "chart-metrics",
      [
        {{type: "scatter", mode: "lines", name: "velocity", x: timeValues, y: speedValues, line: {{color: "#d97706", width: 3}}}},
        {{type: "scatter", mode: "lines", name: "vx", x: timeValues, y: vxValues, line: {{color: "#8e3b2e", width: 3}}, visible: "legendonly"}},
        {{type: "scatter", mode: "lines", name: "vy", x: timeValues, y: vyValues, line: {{color: "#3f6ad8", width: 3}}, visible: "legendonly"}},
        {{type: "scatter", mode: "lines", name: "thrust", x: timeValues, y: thrustValues, line: {{color: "#0e6b60", width: 3}}, yaxis: "y2"}},
        {{type: "scatter", mode: "lines", name: "thrust x", x: timeValues, y: thrustXValues, line: {{color: "#0b7285", width: 2, dash: "dot"}}, yaxis: "y2", visible: "legendonly"}},
        {{type: "scatter", mode: "lines", name: "thrust y", x: timeValues, y: thrustYValues, line: {{color: "#2b8a3e", width: 2, dash: "dash"}}, yaxis: "y2", visible: "legendonly"}},
      ],
      layoutBase("Flight Metrics", {{
        hovermode: "x unified",
        xaxis: {{title: "Time (s)"}},
        yaxis: {{title: "Velocity", zeroline: true}},
        yaxis2: {{title: "Thrust", overlaying: "y", side: "right", zeroline: true}},
      }}),
      baseConfig,
    );
  </script>
</body>
</html>
"""
