#!/usr/bin/env python3
"""Smoke test: schedule assignee must surface on 当日任务 / daily-report.

Reproduces the mismatch where PhaseWorkItem has an assignee but the linked
Task.assignee_user_id is null — daily views previously showed 未指派.

Expects a running API with PLANFLOW_AUTH_MODE=dev.
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from datetime import date, timedelta
from pathlib import Path

import httpx
import jwt
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

BASE = os.getenv("PLANFLOW_API_BASE", "http://127.0.0.1:8000")


def mint_token(sub: str, email: str, name: str) -> str:
    secret = os.getenv("PLANFLOW_DEV_JWT_SECRET", "dev-only-change-me")
    now = int(time.time())
    return jwt.encode(
        {
            "sub": sub,
            "email": email,
            "name": name,
            "iat": now,
            "exp": now + 3600,
        },
        secret,
        algorithm="HS256",
    )


def main() -> int:
    stamp = int(time.time())
    headers = {
        "Authorization": f"Bearer {mint_token(f'user_dev_asg_{stamp}', f'asg{stamp}@example.com', 'xr')}"
    }
    start = date.today()
    end = start + timedelta(days=10)

    with httpx.Client(base_url=BASE, timeout=30.0) as client:
        me = client.get("/me", headers=headers)
        me.raise_for_status()
        user_id = me.json()["id"]
        display = me.json().get("display_name") or "xr"

        team = client.post(
            "/teams",
            headers=headers,
            json={"name": f"Assignee Sync Team {stamp}"},
        )
        team.raise_for_status()
        team_id = team.json()["id"]

        project = client.post(
            f"/teams/{team_id}/projects",
            headers=headers,
            json={
                "name": f"Assignee Sync Project {stamp}",
                "planned_start": start.isoformat(),
                "planned_end": end.isoformat(),
                "owner_user_id": user_id,
                "member_daily_hours": 6,
            },
        )
        project.raise_for_status()
        project_id = project.json()["id"]

        # Unassigned task due today (simulates imported / drifted daily row).
        task = client.post(
            f"/teams/{team_id}/projects/{project_id}/tasks",
            headers=headers,
            json={
                "title": "确认项目目标与关键指标（120名达人、100条发布、200条拍摄）",
                "due_date": start.isoformat(),
            },
        )
        task.raise_for_status()
        task_id = task.json()["id"]
        if task.json().get("assignee_user_id"):
            print("ERROR: new task should start unassigned", file=sys.stderr)
            return 1

        # Minimal schedule so we can attach a work item to that task.
        gen = client.post(
            f"/teams/{team_id}/projects/{project_id}/cycle-schedule/generate",
            headers=headers,
            json={
                "replace_existing": True,
                "seed_mode": "phases_only",
                "phase_count": 1,
                "create_tasks": False,
            },
        )
        if gen.status_code >= 400:
            # phases_only may be restricted; fall back to placeholders.
            gen = client.post(
                f"/teams/{team_id}/projects/{project_id}/cycle-schedule/generate",
                headers=headers,
                json={
                    "replace_existing": True,
                    "seed_mode": "placeholders",
                    "phase_count": 1,
                    "create_tasks": False,
                },
            )
        gen.raise_for_status()
        phases = gen.json()["phases"]
        if not phases:
            print("ERROR: no phases after generate", gen.json(), file=sys.stderr)
            return 1
        phase_id = phases[0]["id"]

        # Link unassigned task to a NEW work item that IS assigned (pre-fix desync shape).
        created = client.post(
            f"/teams/{team_id}/projects/{project_id}/cycle-schedule/phases/{phase_id}/work-items",
            headers=headers,
            json={
                "title": "确认项目目标与关键指标（120名达人、100条发布、200条拍摄）",
                "assignee_user_id": user_id,
                "task_id": task_id,
                "planned_start": start.isoformat(),
                "planned_end": start.isoformat(),
                "estimated_hours": 4,
            },
        )
        created.raise_for_status()
        item = created.json()
        if item.get("assignee_user_id") != user_id:
            print("ERROR: work item assignee not saved", item, file=sys.stderr)
            return 1
        if item.get("task_id") != task_id:
            print("ERROR: work item not linked to task", item, file=sys.stderr)
            return 1

        # create_work_item should have pushed assignee onto the linked task.
        refreshed = client.get(
            f"/teams/{team_id}/projects/{project_id}/tasks",
            headers=headers,
        )
        refreshed.raise_for_status()
        linked = next(t for t in refreshed.json()["tasks"] if t["id"] == task_id)
        if linked.get("assignee_user_id") != user_id:
            print(
                "ERROR: linked task still unassigned after work-item create",
                linked,
                file=sys.stderr,
            )
            return 1
        print("create_work_item pushed assignee onto task OK")

        # Force desync: clear task assignee while restoring work-item assignee
        # (simulates historical drift before bidirectional sync).
        cleared = client.patch(
            f"/teams/{team_id}/projects/{project_id}/tasks/{task_id}",
            headers=headers,
            json={"clear_assignee": True},
        )
        cleared.raise_for_status()
        # Clearing the task also clears the linked work item now — re-assign on schedule.
        patched = client.patch(
            f"/teams/{team_id}/projects/{project_id}/cycle-schedule/work-items/{item['id']}",
            headers=headers,
            json={"assignee_user_id": user_id},
        )
        patched.raise_for_status()

        daily = client.get(
            f"/teams/{team_id}/projects/{project_id}/daily-tasks",
            headers=headers,
            params={"view_date": start.isoformat()},
        )
        daily.raise_for_status()
        cards = daily.json()["tasks"]
        card = next((c for c in cards if c["task"]["id"] == task_id), None)
        if card is None:
            print("ERROR: daily-tasks missing the linked task", daily.json(), file=sys.stderr)
            return 1
        if not card.get("assignee_display_name"):
            print(
                "ERROR: daily-tasks still shows unassigned (null assignee_display_name)",
                card,
                file=sys.stderr,
            )
            return 1
        if card["task"].get("assignee_user_id") != user_id:
            print(
                "ERROR: daily-tasks task.assignee_user_id not healed",
                card,
                file=sys.stderr,
            )
            return 1
        print(
            "daily-tasks assignee OK:",
            json.dumps(
                {
                    "assignee_display_name": card["assignee_display_name"],
                    "expected_name_hint": display,
                },
                ensure_ascii=False,
            ),
        )

        report = client.get(
            f"/teams/{team_id}/projects/{project_id}/daily-report",
            headers=headers,
            params={"view_date": start.isoformat()},
        )
        report.raise_for_status()
        row = next(
            (w for w in report.json()["work_items"] if w["task_id"] == task_id),
            None,
        )
        if row is None or not row.get("assignee_display_name"):
            print("ERROR: daily-report still 未指派", report.json(), file=sys.stderr)
            return 1
        print("daily-report assignee OK:", row["assignee_display_name"])

        # Heal path: null out task assignee in DB-shaped way via work-item still assigned.
        # Clear via task (also clears WI), then set WI only through a second create+link
        # isn't available — instead patch WI after manually breaking via raw clear on task
        # then patch WI (already covered). Also verify heal when task is cleared without
        # going through API sync: patch WI first, then use sync-task after simulating
        # drift by clearing assignee on task and re-setting WI without calling sync.
        # Re-break: clear assignee on task (clears WI), set WI assignee (syncs to task).
        # Then verify heal: we need task null + WI set. Temporary: create another task.
        orphan = client.post(
            f"/teams/{team_id}/projects/{project_id}/tasks",
            headers=headers,
            json={"title": "跟进达人内容产出", "due_date": start.isoformat()},
        )
        orphan.raise_for_status()
        orphan_id = orphan.json()["id"]
        wi2 = client.post(
            f"/teams/{team_id}/projects/{project_id}/cycle-schedule/phases/{phase_id}/work-items",
            headers=headers,
            json={
                "title": "跟进达人内容产出",
                "assignee_user_id": user_id,
                "task_id": orphan_id,
                "planned_start": start.isoformat(),
                "planned_end": start.isoformat(),
                "estimated_hours": 2,
            },
        )
        wi2.raise_for_status()
        # Break lockstep using SQL-less approach: clear_assignee on task syncs WI to null,
        # so re-assign WI. That already tests sync. For pure heal, rely on create push above.
        # Force heal by clearing only through a direct work-item state: assign WI, then
        # clear task via patch which clears WI — can't leave WI assigned via public API.
        # Heal is still exercised if create_work_item failed to push (regression covered).
        # Force historical desync: WI assigned, Task.assignee null (DB-level).
        from app.db import get_session_factory
        from app.models import PhaseWorkItem, Task as TaskModel

        SessionLocal = get_session_factory()
        with SessionLocal() as session:
            row = session.query(TaskModel).filter(TaskModel.id == orphan_id).one()
            row.assignee_user_id = None
            wi_row = (
                session.query(PhaseWorkItem)
                .filter(PhaseWorkItem.task_id == orphan_id)
                .one()
            )
            wi_row.assignee_user_id = uuid.UUID(user_id)
            session.commit()

        daily_heal = client.get(
            f"/teams/{team_id}/projects/{project_id}/daily-tasks",
            headers=headers,
            params={"view_date": start.isoformat()},
        )
        daily_heal.raise_for_status()
        healed = next(
            c for c in daily_heal.json()["tasks"] if c["task"]["id"] == orphan_id
        )
        if healed["task"].get("assignee_user_id") != user_id:
            print("ERROR: heal did not restore task assignee", healed, file=sys.stderr)
            return 1
        if not healed.get("assignee_display_name"):
            print("ERROR: heal left assignee_display_name empty", healed, file=sys.stderr)
            return 1
        print("heal-from-work-item OK:", healed["assignee_display_name"])

    print("verify_schedule_daily_assignee.py: ALL OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
