from __future__ import annotations

import runtime.eval.headless_stats as headless_stats


class _Bot:
    def __init__(self, text: str) -> None:
        self._text = text

    def get_headless_stats(self) -> str:
        return self._text


def test_print_headless_stats_formats_actor_and_bot_lines(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(
        headless_stats, "build_headless_stats", lambda _actor, _terrain: "ship:ok"
    )

    headless_stats.print_headless_stats(
        elapsed_time=12.34,
        active_actor=object(),
        terrain=object(),
        actor_bots={
            "a": _Bot("bot:a"),
            "b": _Bot(""),
        },
    )

    out = capsys.readouterr().out.strip()
    assert out == "t= 12.34 | ship:ok | bot:a"
