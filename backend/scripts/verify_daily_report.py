#!/usr/bin/env python3
"""Smoke test: per-user project daily reports + owner sync view.

Expects a running API with PLANFLOW_AUTH_MODE=dev.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import date
from pathlib import Path

import httpx
import jwt
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

BASE = os.getenv("PLANFLOW_API_BASE", "http://127.0.0.1:8000")


def mint_token(sub: str, email: str, name: str | None = None) -> str:
    secret = os.getenv("PLANFLOW_DEV_JWT_SECRET", "dev-only-change-me")
    now = int(time.time())
    return jwt.encode(
        {
            "sub": sub,
            "email": email,
            "name": name or sub,
            "iat": now,
            "exp": now + 3600,
        },
        secret,
        algorithm="HS256",
    )


def main() -> int:
    stamp = int(time.time())
    owner_h = {
        "Authorization": f"Bearer {mint_token(f'user_dev_report_o_{stamp}', f'report_o_{stamp}@example.com', 'Owner')}"
    }
    member_h = {
        "Authorization": f"Bearer {mint_token(f'user_dev_report_m_{stamp}', f'report_m_{stamp}@example.com', 'Member')}"
    }
    today = date.today().isoformat()

    with httpx.Client(base_url=BASE, timeout=30.0) as client:
        owner_id = client.get("/me", headers=owner_h).json()["id"]
        member_id = client.get("/me", headers=member_h).json()["id"]

        team = client.post(
            "/teams",
            headers=owner_h,
            json={"name": f"Report Team {stamp}"},
        )
        team.raise_for_status()
        team_id = team.json()["id"]

        invite = client.post(
            f"/teams/{team_id}/invites",
            headers=owner_h,
            json={"email": f"report_m_{stamp}@example.com", "role": "member"},
        )
        invite.raise_for_status()
        client.post(
            f"/invites/{invite.json()['token']}/accept", headers=member_h
        ).raise_for_status()

        project = client.post(
            f"/teams/{team_id}/projects",
            headers=owner_h,
            json={
                "name": f"Report Project {stamp}",
                "owner_user_id": owner_id,
            },
        )
        project.raise_for_status()
        project_id = project.json()["id"]

        path = f"/teams/{team_id}/projects/{project_id}/daily-report"

        # Member saves own draft
        saved_m = client.put(
            path,
            headers=member_h,
            params={"view_date": today},
            json={
                "summary_text": "成员进展：联调中",
                "next_actions": "1. 补测试",
            },
        )
        saved_m.raise_for_status()
        body_m = saved_m.json()
        if body_m["user_id"] != member_id:
            print("ERROR: member user_id mismatch", body_m, file=sys.stderr)
            return 1
        if body_m["summary_text"] != "成员进展：联调中":
            print("ERROR: member summary not saved", body_m, file=sys.stderr)
            return 1
        if body_m["status"] != "draft":
            print("ERROR: expected draft", body_m, file=sys.stderr)
            return 1
        if body_m.get("can_view_all"):
            print("ERROR: member should not can_view_all", body_m, file=sys.stderr)
            return 1
        if body_m.get("submissions"):
            print("ERROR: member should not see submissions", body_m, file=sys.stderr)
            return 1
        print("member draft OK")

        # Owner saves a different personal report (must not overwrite member)
        saved_o = client.put(
            path,
            headers=owner_h,
            params={"view_date": today},
            json={
                "summary_text": "负责人进展：风险评审",
                "next_actions": "1. 同步客户",
            },
        )
        saved_o.raise_for_status()
        body_o = saved_o.json()
        if body_o["user_id"] != owner_id:
            print("ERROR: owner user_id mismatch", body_o, file=sys.stderr)
            return 1
        if body_o["summary_text"] != "负责人进展：风险评审":
            print("ERROR: owner summary not saved", body_o, file=sys.stderr)
            return 1
        if not body_o.get("can_view_all"):
            print("ERROR: owner should can_view_all", body_o, file=sys.stderr)
            return 1

        # Owner aggregate before sync: drafts hide content
        by_user = {s["user_id"]: s for s in body_o["submissions"]}
        if member_id not in by_user or owner_id not in by_user:
            print("ERROR: submissions missing users", body_o["submissions"], file=sys.stderr)
            return 1
        if by_user[member_id]["status"] != "draft":
            print("ERROR: member submission should be draft", by_user[member_id], file=sys.stderr)
            return 1
        if by_user[member_id]["summary_text"] is not None:
            print("ERROR: draft content must be hidden", by_user[member_id], file=sys.stderr)
            return 1
        print("owner sees drafts without content OK")

        # Member still has own text (uniqueness / ownership)
        again_m = client.get(path, headers=member_h, params={"view_date": today})
        again_m.raise_for_status()
        if again_m.json()["summary_text"] != "成员进展：联调中":
            print("ERROR: member report overwritten", again_m.json(), file=sys.stderr)
            return 1
        print("per-user uniqueness OK")

        # Complete/sync member report
        done_m = client.post(
            f"{path}/complete",
            headers=member_h,
            params={"view_date": today},
            json={
                "summary_text": "成员进展：联调完成",
                "next_actions": "1. 提测",
            },
        )
        done_m.raise_for_status()
        if done_m.json()["status"] != "completed":
            print("ERROR: complete failed", done_m.json(), file=sys.stderr)
            return 1
        print("member complete OK")

        # Owner now sees completed content
        owner_view = client.get(path, headers=owner_h, params={"view_date": today})
        owner_view.raise_for_status()
        by_user = {s["user_id"]: s for s in owner_view.json()["submissions"]}
        mem_sub = by_user[member_id]
        if mem_sub["status"] != "completed":
            print("ERROR: expected completed", mem_sub, file=sys.stderr)
            return 1
        if mem_sub["summary_text"] != "成员进展：联调完成":
            print("ERROR: owner cannot see synced content", mem_sub, file=sys.stderr)
            return 1
        if by_user[owner_id]["status"] != "draft":
            print("ERROR: owner own still draft", by_user[owner_id], file=sys.stderr)
            return 1
        print("owner synced view OK")

        # Owner completes own too
        client.post(
            f"{path}/complete",
            headers=owner_h,
            params={"view_date": today},
            json={
                "summary_text": "负责人进展：风险已关闭",
                "next_actions": "1. 发周报",
            },
        ).raise_for_status()

        final = client.get(path, headers=owner_h, params={"view_date": today})
        final.raise_for_status()
        completed = [
            s for s in final.json()["submissions"] if s["status"] == "completed"
        ]
        if len(completed) != 2:
            print("ERROR: expected 2 completed", final.json()["submissions"], file=sys.stderr)
            return 1
        print("both completed OK")

        unauth = client.get(path, params={"view_date": today})
        if unauth.status_code != 401:
            print(f"ERROR: expected 401, got {unauth.status_code}", file=sys.stderr)
            return 1

        print(
            "summary:",
            json.dumps(
                {
                    "completed": len(completed),
                    "can_view_all": final.json()["can_view_all"],
                },
                ensure_ascii=False,
            ),
        )

    print("verify_daily_report.py: ALL OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
