"""Bot/actor session management.

DEPRECATED: Import from bot_framework.bot_actor_session instead.
This module is kept for backward compatibility and will be removed in a future release.
"""

from __future__ import annotations

import warnings

from bot_framework.bot_actor_session import (
    active_actor_bot,
    attach_primary_bot,
    ensure_bot_identity_fields,
    install_actor_bot,
    install_world_actor_bots,
)

warnings.warn(
    "runtime.actor_session is deprecated; import from bot_framework.bot_actor_session instead.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = [
    "active_actor_bot",
    "attach_primary_bot",
    "ensure_bot_identity_fields",
    "install_actor_bot",
    "install_world_actor_bots",
]
