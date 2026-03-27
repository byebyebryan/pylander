from __future__ import annotations

from pathlib import Path

import pytest


pytestmark = pytest.mark.skills

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_only_surviving_skill_directories_exist() -> None:
    skill_root = REPO_ROOT / ".agents" / "skills"
    assert skill_root.is_dir()
    assert not (REPO_ROOT / "skills").exists()

    actual = {path.name for path in skill_root.iterdir() if path.is_dir()}
    assert actual == {
        "pylander-benchmark-runner",
        "pylander-commit-manager",
    }


def test_surviving_benchmark_wrappers_exist() -> None:
    launchers = [
        ".agents/skills/pylander-benchmark-runner/scripts/build_selector_pack.py",
        ".agents/skills/pylander-benchmark-runner/scripts/run_cached_benchmark.py",
        ".agents/skills/pylander-benchmark-runner/scripts/gen_bench_bundle.py",
        ".agents/skills/pylander-benchmark-runner/scripts/serve_outputs.py",
        ".agents/skills/pylander-commit-manager/SKILL.md",
    ]
    for rel in launchers:
        assert (REPO_ROOT / rel).is_file(), rel
