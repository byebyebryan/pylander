from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


pytestmark = pytest.mark.skills

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    ("subcommand", "expected_token"),
    [
        ("selectors", "Build Pylander benchmark selector packs"),
        ("run", "Run cached Pylander benchmarks with optional baseline compare"),
        ("report", "Write a static HTML bundle from existing benchmark artifacts"),
        ("bundle", "Run cached benchmark and write a static HTML bundle"),
        ("serve", "Serve the local outputs directory over HTTP"),
    ],
)
def test_benchmark_skill_cli_help(subcommand: str, expected_token: str) -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "app.bench", subcommand, "--help"],
        cwd=str(REPO_ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    assert proc.returncode == 0, proc.stdout
    assert "usage:" in proc.stdout
    assert expected_token in proc.stdout


def test_benchmark_skill_cli_top_level_help() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "app.bench", "--help"],
        cwd=str(REPO_ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    assert proc.returncode == 0, proc.stdout
    assert "Pylander benchmark workflow CLI" in proc.stdout
    assert "selectors" in proc.stdout
    assert "report" in proc.stdout
