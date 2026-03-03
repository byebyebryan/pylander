from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ParsedSelector:
    level_name: str
    scenario_name: str | None
    seed_token: str | None


def parse_seed_spec(spec: str) -> list[int]:
    values: list[int] = []
    for token in (p.strip() for p in spec.split(",")):
        if not token:
            continue
        if "-" in token:
            left, right = token.split("-", 1)
            start = int(left.strip())
            end = int(right.strip())
            step = 1 if end >= start else -1
            values.extend(range(start, end + step, step))
        else:
            values.append(int(token))

    out: list[int] = []
    seen: set[int] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def parse_selector(
    raw_selector: str | None,
    *,
    default_level: str | None,
    known_levels: set[str],
) -> ParsedSelector:
    selector = "" if raw_selector is None else str(raw_selector).strip()
    if not selector:
        if default_level is None:
            raise ValueError("Missing selector and no default level is available")
        return ParsedSelector(level_name=default_level, scenario_name=None, seed_token=None)

    parts = selector.split(":")
    if len(parts) > 3:
        raise ValueError(
            f"Invalid selector '{selector}'. Expected format 'level[:scenario[:seed]]'"
        )

    level_name = parts[0].strip()
    if not level_name:
        raise ValueError(
            f"Invalid selector '{selector}'. Level is required in 'level[:scenario[:seed]]'"
        )
    if level_name not in known_levels:
        known = ", ".join(sorted(known_levels))
        raise ValueError(f"Unknown level '{level_name}'. Expected one of: {known}")

    scenario_name = None
    if len(parts) >= 2:
        scenario = parts[1].strip()
        scenario_name = scenario if scenario else None

    seed_token = None
    if len(parts) >= 3:
        seed = parts[2].strip()
        seed_token = seed if seed else None

    return ParsedSelector(
        level_name=level_name,
        scenario_name=scenario_name,
        seed_token=seed_token,
    )

