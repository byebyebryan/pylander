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


def test_surviving_skill_docs_and_benchmark_cli_exist() -> None:
    launchers = [
        ".agents/skills/pylander-benchmark-runner/SKILL.md",
        ".agents/skills/pylander-commit-manager/SKILL.md",
        "app/bench.py",
    ]
    for rel in launchers:
        assert (REPO_ROOT / rel).is_file(), rel


def test_benchmark_skill_no_longer_uses_local_wrapper_scripts() -> None:
    scripts_root = REPO_ROOT / ".agents" / "skills" / "pylander-benchmark-runner" / "scripts"
    assert not any(scripts_root.glob("*.py"))
