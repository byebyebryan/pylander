"""Tests for pygbag web entrypoint and browser isolation."""

from __future__ import annotations

import sys


def test_pygbag_module_imports_cleanly():
    """pygbag/__init__.py imports without bot_framework or tooling."""
    import pygbag

    assert hasattr(pygbag, "EMSCRIPTEN")
    assert hasattr(pygbag, "is_browser")


def test_is_browser_returns_bool():
    """is_browser returns a boolean."""
    import pygbag

    result = pygbag.is_browser()
    assert isinstance(result, bool)


def test_emscripten_detection():
    """EMSCRIPTEN constant reflects sys.emscripten."""
    import pygbag

    assert pygbag.EMSCRIPTEN == hasattr(sys, "emscripten")


def test_build_web_game_imports_cleanly():
    """build_web_game function is accessible without triggering unwanted imports."""
    import pygbag

    assert callable(pygbag.build_web_game)


def test_no_bot_framework_imported_on_module_load():
    """Importing pygbag does not load bot_framework modules."""
    before = set(sys.modules.keys())

    import pygbag  # noqa: F401 - import is intentional for side effect

    after = set(sys.modules.keys())
    new_modules = after - before

    bot_modules = [m for m in new_modules if m.startswith("bot_framework")]
    assert not bot_modules, f"bot_framework imported: {bot_modules}"


def test_no_tooling_imported_on_module_load():
    """Importing pygbag does not load tooling modules."""
    before = set(sys.modules.keys())

    import pygbag  # noqa: F401 - import is intentional for side effect

    after = set(sys.modules.keys())
    new_modules = after - before

    tooling_modules = [m for m in new_modules if m.startswith("tooling")]
    assert not tooling_modules, f"tooling imported: {tooling_modules}"


def test_no_app_imported_on_module_load():
    """Importing pygbag does not load app modules."""
    before = set(sys.modules.keys())

    import pygbag  # noqa: F401 - import is intentional for side effect

    after = set(sys.modules.keys())
    new_modules = after - before

    app_modules = [m for m in new_modules if m.startswith("app.")]
    assert not app_modules, f"app imported: {app_modules}"


def test_game_still_accessible_after_pygbag_import():
    """Game modules are still accessible after importing pygbag."""
    import pygbag  # noqa: F401 - import is intentional for side effect

    from game.levels.registry import create_level

    level = create_level("flat")
    assert level is not None


def test_build_web_game_has_clean_call_time_imports():
    """Calling build_web_game() does not import bot_framework or tooling."""
    import pygbag  # noqa: F401 - import is intentional for side effect

    before = set(sys.modules.keys())
    _ = pygbag.build_web_game("flat", seed=42, width=800, height=600)
    after = set(sys.modules.keys())

    new_modules = after - before
    bot_modules = [m for m in new_modules if m.startswith("bot_framework")]
    tooling_modules = [m for m in new_modules if m.startswith("tooling")]
    app_modules = [m for m in new_modules if m.startswith("app.")]

    assert not bot_modules, f"bot_framework imported at call time: {bot_modules}"
    assert not tooling_modules, f"tooling imported at call time: {tooling_modules}"
    assert not app_modules, f"app imported at call time: {app_modules}"
