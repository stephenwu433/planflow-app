#!/usr/bin/env python3
"""Smoke test: custom free-text job titles on team + project members."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import jwt
from dotenv import load_dotenv
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
os.environ["PLANFLOW_AUTH_MODE"] = "dev"
os.environ.setdefault("PLANFLOW_DEV_JWT_SECRET", "dev-only-change-me")

sys.path.insert(0, str(ROOT))
from app.job_titles import coerce_suggested_job, normalize_job_title  # noqa: E402
from app.main import app  # noqa: E402


def mint(sub: str, email: str | None = None) -> dict[str, str]:
    secret = os.environ["PLANFLOW_DEV_JWT_SECRET"]
    now = int(time.time())
    payload: dict = {"sub": sub, "iat": now, "exp": now + 3600}
    if email:
        payload["email"] = email
    token = jwt.encode(payload, secret, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def test_normalize_unit() -> None:
    assert normalize_job_title("  PM  ") == "pm"
    assert normalize_job_title("产品经理") == "pm"
    assert normalize_job_title("前端工程师") == "前端工程师"
    assert normalize_job_title("  ") is None
    try:
        normalize_job_title("x" * 41)
        raise AssertionError("expected length rejection")
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 400
    assert coerce_suggested_job("前端工程师", available_jobs=["前端工程师", "pm"]) == "前端工程师"
    assert coerce_suggested_job("unknown", available_jobs=["pm", "other"]) == "other"
    print("normalize_job_title unit OK")


def main() -> int:
    test_normalize_unit()

    client = TestClient(app)
    stamp = int(time.time())
    owner = mint(f"user_dev_custom_job_owner_{stamp}", email=f"owner_{stamp}@example.com")
    member = mint(f"user_dev_custom_job_member_{stamp}", email=f"member_{stamp}@example.com")

    team = client.post("/teams", headers=owner, json={"name": f"Custom Job Team {stamp}"})
    team.raise_for_status()
    team_id = team.json()["id"]

    me = client.get("/me", headers=owner)
    me.raise_for_status()
    owner_id = me.json()["id"]

    # Preset still works
    preset = client.patch(
        f"/teams/{team_id}/members/{owner_id}",
        headers=owner,
        json={"job_title": "designer"},
    )
    preset.raise_for_status()
    assert preset.json()["job_title"] == "designer"

    # Custom free-text title
    custom = client.patch(
        f"/teams/{team_id}/members/{owner_id}",
        headers=owner,
        json={"job_title": "  前端工程师  "},
    )
    custom.raise_for_status()
    assert custom.json()["job_title"] == "前端工程师", custom.json()
    print("team custom job_title OK")

    # Chinese preset label maps to key
    mapped = client.patch(
        f"/teams/{team_id}/members/{owner_id}",
        headers=owner,
        json={"job_title": "运营"},
    )
    mapped.raise_for_status()
    assert mapped.json()["job_title"] == "ops"

    # Invite a second member and set custom title on them via project roster
    invite = client.post(
        f"/teams/{team_id}/invites",
        headers=owner,
        json={"role": "member"},
    )
    invite.raise_for_status()
    token_path = invite.json()["token"]
    accepted = client.post(f"/invites/{token_path}/accept", headers=member)
    accepted.raise_for_status()
    member_id = accepted.json()["user_id"]

    project = client.post(
        f"/teams/{team_id}/projects",
        headers=owner,
        json={"name": f"Custom Job Project {stamp}"},
    )
    project.raise_for_status()
    project_id = project.json()["id"]

    added = client.post(
        f"/teams/{team_id}/projects/{project_id}/members",
        headers=owner,
        json={"user_id": member_id, "job_title": "全栈开发"},
    )
    added.raise_for_status()
    body = added.json()
    assert body["job_title"] == "全栈开发", body
    assert body["job_title_label"] == "全栈开发", body
    print("project custom job_title OK")

    # Reject overlong title (Pydantic max_length → 422, or normalize → 400)
    too_long = client.patch(
        f"/teams/{team_id}/members/{owner_id}",
        headers=owner,
        json={"job_title": "超" * 41},
    )
    if too_long.status_code not in (400, 422):
        print(
            f"ERROR: expected 400/422 for long title, got {too_long.status_code}",
            file=sys.stderr,
        )
        return 1
    print("overlong job_title rejected OK")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
