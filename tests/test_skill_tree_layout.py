from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_agents_skills_is_only_skill_source_tree() -> None:
    assert (REPO_ROOT / ".agents" / "skills").is_dir()
    assert not (REPO_ROOT / "skills").exists()


def test_representative_skill_launchers_exist_under_agents_tree() -> None:
    launchers = [
        ".agents/skills/pylander-benchmark-runner/scripts/build_selector_pack.py",
        ".agents/skills/pylander-tune-routing-planner/scripts/route_tuning.py",
        ".agents/skills/pylander-telemetry-analyzer/scripts/analyze_telemetry.py",
    ]
    for rel in launchers:
        assert (REPO_ROOT / rel).is_file(), rel
