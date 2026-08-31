"""pytest path bootstrap。"""

from __future__ import annotations

import sys
from pathlib import Path

WEB = Path(__file__).resolve().parents[1]
ROOT = WEB.parent
for p in (ROOT, WEB):
    s = str(p)
    if s not in sys.path:
        sys.path.insert(0, s)
