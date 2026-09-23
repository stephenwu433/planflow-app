"""Keep Task.assignee_user_id aligned with linked schedule work items.

Schedule edits live on PhaseWorkItem; 「当日任务」 / daily report read Task.
These helpers heal and sync assignee across that link so assigned schedule
work does not appear as 未指派 in daily views.
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.models import PhaseWorkItem, Task, User


def user_label(user: User) -> str:
    return (
        (user.display_name or "").strip()
        or (user.email or "").strip()
        or (user.clerk_user_id or "").strip()
        or f"成员 {str(user.id)[:8]}"
    )


def assignee_label(
    assignee_id: uuid.UUID | None,
    names: dict[uuid.UUID, str],
) -> str | None:
    """Human label for an assignee id; never pretend unassigned when id is set."""
    if assignee_id is None:
        return None
    label = names.get(assignee_id)
    if label:
        return label
    return f"未知成员（{str(assignee_id)[:8]}）"


def load_assignee_names(
    db: Session, assignee_ids: set[uuid.UUID]
) -> dict[uuid.UUID, str]:
    names: dict[uuid.UUID, str] = {}
    if not assignee_ids:
        return names
    for user in db.query(User).filter(User.id.in_(assignee_ids)).all():
        names[user.id] = user_label(user)
    return names


def heal_task_assignee_from_work_item(db: Session, task: Task) -> bool:
    """Copy PhaseWorkItem.assignee onto Task when the task assignee is empty.

    Returns True when the task row was updated (caller should commit).
    """
    if task.assignee_user_id is not None:
        return False
    item = (
        db.query(PhaseWorkItem)
        .filter(PhaseWorkItem.task_id == task.id)
        .order_by(PhaseWorkItem.updated_at.desc())
        .first()
    )
    if item is None or item.assignee_user_id is None:
        return False
    task.assignee_user_id = item.assignee_user_id
    return True


def heal_tasks_assignees_from_work_items(db: Session, tasks: list[Task]) -> bool:
    """Heal a list of tasks; returns True if any row changed."""
    changed = False
    for task in tasks:
        if heal_task_assignee_from_work_item(db, task):
            changed = True
    return changed


def sync_work_items_assignee_from_task(db: Session, task: Task) -> None:
    """Push Task.assignee onto every schedule work item linked to this task."""
    items = (
        db.query(PhaseWorkItem).filter(PhaseWorkItem.task_id == task.id).all()
    )
    for item in items:
        item.assignee_user_id = task.assignee_user_id
