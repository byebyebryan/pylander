"""Pygbag web entry point for pylander."""

from __future__ import annotations

import asyncio
import os
import traceback
from typing import Any

os.environ["PYLANDER_PHYSICS"] = "euler"

# Import pygame at module level so that pygame.__init__ runs import_cython,
# registering pygame.math (and other submodules) in sys.modules before any
# game module tries to import them.
import pygame  # noqa: F401


async def _main() -> None:
    import platform

    window: Any | None = getattr(platform, "window", None)

    try:
        if window is not None:
            window.infobox.innerText = "importing game..."
            window.infobox.style.display = "block"
    except Exception:
        pass

    try:
        from game.runtime.web import run_web_game

        try:
            if window is not None:
                window.infobox.style.display = "none"
        except Exception:
            pass
        await run_web_game()
    except Exception as exc:
        msg = f"FATAL: {exc}\n{traceback.format_exc()}"
        print(msg)
        try:
            if window is not None:
                window.infobox.innerText = msg[:500]
                window.infobox.style.display = "block"
                window.infobox.style.background = "red"
                window.infobox.style.color = "white"
                window.infobox.style.whiteSpace = "pre"
                window.infobox.style.fontSize = "12px"
        except Exception:
            pass
        # Keep alive so error stays visible
        while True:
            await asyncio.sleep(1)


asyncio.run(_main())
