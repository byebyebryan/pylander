from __future__ import annotations

from app.reporting import print_headless_results


def test_print_headless_results_includes_plot_bundle_metadata(capsys) -> None:
    print_headless_results(
        {
            "state": "landed",
            "success": True,
            "plot_paths": ["outputs/plots/overview/case_a.png"],
            "plot_manifest_path": "outputs/plots/case_a/manifest.json",
            "plot_bundle_dir": "outputs/plots/case_a",
        }
    )

    output = capsys.readouterr().out
    assert "outputs/plots/overview/case_a.png" in output
    assert "outputs/plots/case_a/manifest.json" in output
    assert "outputs/plots/case_a" in output
