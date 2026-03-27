from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
_AGENTS_ROOT = (_REPO_ROOT / ".agents").resolve()
for candidate in (_AGENTS_ROOT, _REPO_ROOT):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from app.plot_pack import main  # noqa: E402


if __name__ == "__main__":
    main()
