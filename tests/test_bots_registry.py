from __future__ import annotations

import pytest

from bot_framework.bots import registry


def test_list_available_bots_only_reports_loadable_bots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class DummyBot:
        pass

    def stub_bot_classes():
        return {"plunge": DummyBot}, {"pdg": "No module named 'cvxpy'"}

    monkeypatch.setattr(registry, "_bot_classes", stub_bot_classes)

    assert registry.list_available_bots() == ["plunge"]


def test_load_bot_class_reports_unavailable_bot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def stub_bot_classes():
        return {}, {"pdg": "No module named 'cvxpy'"}

    monkeypatch.setattr(registry, "_bot_classes", stub_bot_classes)

    with pytest.raises(ValueError, match="Bot 'pdg' is unavailable"):
        registry.load_bot_class("pdg")


def test_load_bot_class_reports_unknown_bot(monkeypatch: pytest.MonkeyPatch) -> None:
    def stub_bot_classes():
        return {}, {}

    monkeypatch.setattr(registry, "_bot_classes", stub_bot_classes)

    with pytest.raises(ValueError, match="Unknown bot 'mystery'"):
        registry.load_bot_class("mystery")


def test_create_bot_reports_init_time_missing_dependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class MissingDepBot:
        def __init__(self) -> None:
            raise ModuleNotFoundError("No module named 'cvxpy'")

    def stub_load_bot_class(_name: str):
        return MissingDepBot

    monkeypatch.setattr(registry, "load_bot_class", stub_load_bot_class)

    with pytest.raises(ValueError, match="failed to initialize"):
        registry.create_bot("pdg")
