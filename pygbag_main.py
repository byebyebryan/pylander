"""Pygbag web entry point for pylander."""

from __future__ import annotations

import asyncio
import os
import traceback

os.environ["PYLANDER_PHYSICS"] = "euler"

# Import pygame at module level so that pygame.__init__ runs import_cython,
# registering pygame.math (and other submodules) in sys.modules before any
# game module tries to import them.
import pygame  # noqa: F401


async def _main() -> None:
    import platform

    try:
        platform.window.infobox.innerText = "importing game..."
        platform.window.infobox.style.display = "block"
    except Exception:
        pass

    try:
        from game.web import run_web_game

        try:
            platform.window.infobox.style.display = "none"
        except Exception:
            pass
        await run_web_game()
    except Exception as exc:
        msg = f"FATAL: {exc}\n{traceback.format_exc()}"
        print(msg)
        try:
            platform.window.infobox.innerText = msg[:500]
            platform.window.infobox.style.display = "block"
            platform.window.infobox.style.background = "red"
            platform.window.infobox.style.color = "white"
            platform.window.infobox.style.whiteSpace = "pre"
            platform.window.infobox.style.fontSize = "12px"
        except Exception:
            pass
        # Keep alive so error stays visible
        while True:
            await asyncio.sleep(1)


asyncio.run(_main())
