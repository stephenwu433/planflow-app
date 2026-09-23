#!/usr/bin/env python3
"""Unit checks: schedule ↔ task assignee sync helpers (no server required).

Run: python scripts/test_assignee_sync.py
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.assignee_sync import assignee_label, user_label  # noqa: E402
from app.models import User  # noqa: E402


def _user(**kwargs) -> User:
    defaults = {
        "id": uuid.uuid4(),
        "clerk_user_id": "clerk_x",
        "email": None,
        "display_name": None,
    }
    defaults.update(kwargs)
    return User(**defaults)


def main() -> int:
    u = _user(display_name="xr", email="xr@example.com", clerk_user_id="clerk_xr")
    assert user_label(u) == "xr", user_label(u)

    bare = _user(display_name=None, email=None, clerk_user_id="clerk_only")
    assert user_label(bare) == "clerk_only", user_label(bare)

    aid = uuid.uuid4()
    names = {aid: "ll"}
    assert assignee_label(None, names) is None
    assert assignee_label(aid, names) == "ll"
    missing = uuid.UUID("00000000-0000-0000-0000-000000000001")
    assert assignee_label(missing, names) == "未知成员（00000000）", assignee_label(
        missing, names
    )

    print("test_assignee_sync.py: ALL OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
