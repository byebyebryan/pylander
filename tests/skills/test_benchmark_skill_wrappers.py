from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


pytestmark = pytest.mark.skills

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    ("rel_path", "expected_token"),
    [
        (
            ".agents/skills/pylander-benchmark-runner/scripts/build_selector_pack.py",
            "Build Pylander benchmark selector packs",
        ),
        (
            ".agents/skills/pylander-benchmark-runner/scripts/run_cached_benchmark.py",
            "Run cached Pylander benchmarks with optional baseline compare",
        ),
        (
            ".agents/skills/pylander-benchmark-runner/scripts/gen_bench_bundle.py",
            "Run cached benchmark and write a static HTML bundle",
        ),
        (
            ".agents/skills/pylander-benchmark-runner/scripts/serve_outputs.py",
            "Serve the local outputs directory over HTTP",
        ),
    ],
)
def test_benchmark_skill_wrapper_help(rel_path: str, expected_token: str) -> None:
    proc = subprocess.run(
        [sys.executable, str((REPO_ROOT / rel_path).resolve()), "--help"],
        cwd=str(REPO_ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    assert proc.returncode == 0, proc.stdout
    assert "usage:" in proc.stdout
    assert expected_token in proc.stdout
