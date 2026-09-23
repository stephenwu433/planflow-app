"""Per-user project daily report: auto-aggregated tasks + personal narrative."""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.db import get_db
from app.membership import require_team_membership
from app.models import Project, ProjectDailyReport, Task, TaskTimeEntry, TeamMember, User
from app.notifications import notify_report_viewers
from app.schemas import (
    DailyReportResponse,
    DailyReportSaveRequest,
    DailyReportWorkItem,
    MemberDailyReportSubmission,
)

router = APIRouter(
    prefix="/teams/{team_id}/projects/{project_id}/daily-report",
    tags=["daily-report"],
)


def _require_project(
    db: Session, *, team_id: uuid.UUID, project_id: uuid.UUID
) -> Project:
    project = (
        db.query(Project)
        .filter(Project.id == project_id, Project.team_id == team_id)
        .one_or_none()
    )
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _can_view_all(
    *, project: Project, membership: TeamMember, user: User
) -> bool:
    """Team owner/admin or project owner can see everyone's synced reports."""
    if membership.role in {"owner", "admin"}:
        return True
    if project.owner_user_id is not None and project.owner_user_id == user.id:
        return True
    return False


def _auto_summary(
    *,
    day: date,
    day_task_count: int,
    day_hours: float,
    progress: int,
    done: int,
    total: int,
) -> str:
    label = f"{day.month}月{day.day}日"
    if day_task_count == 0 and day_hours <= 0:
        return f"{label}没有此项目任务或工时记录，可切换日期查看，或先在每日任务里添加。"
    parts = [
        f"{label}共有 {day_task_count} 项相关任务",
        f"当日已填工时 {day_hours}h",
        f"项目整体进度 {progress}%（{done}/{total}）",
    ]
    return "，".join(parts) + "。"


def _normalize_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text if text else None


def _get_own_report(
    db: Session, *, project_id: uuid.UUID, day: date, user_id: uuid.UUID
) -> ProjectDailyReport | None:
    return (
        db.query(ProjectDailyReport)
        .filter(
            ProjectDailyReport.project_id == project_id,
            ProjectDailyReport.report_date == day,
            ProjectDailyReport.user_id == user_id,
        )
        .one_or_none()
    )


def _build_submissions(
    db: Session, *, team_id: uuid.UUID, project_id: uuid.UUID, day: date
) -> list[MemberDailyReportSubmission]:
    members = (
        db.query(TeamMember, User)
        .join(User, User.id == TeamMember.user_id)
        .filter(TeamMember.team_id == team_id)
        .order_by(User.display_name.asc().nulls_last(), User.email.asc().nulls_last())
        .all()
    )
    rows = (
        db.query(ProjectDailyReport)
        .filter(
            ProjectDailyReport.project_id == project_id,
            ProjectDailyReport.report_date == day,
        )
        .all()
    )
    by_user = {row.user_id: row for row in rows}

    out: list[MemberDailyReportSubmission] = []
    for membership, user in members:
        del membership  # role unused in submission row
        row = by_user.get(user.id)
        if row is None:
            out.append(
                MemberDailyReportSubmission(
                    user_id=user.id,
                    display_name=user.display_name,
                    email=user.email,
                    status="missing",
                )
            )
            continue
        completed = row.status == "completed"
        out.append(
            MemberDailyReportSubmission(
                user_id=user.id,
                display_name=user.display_name,
                email=user.email,
                status=row.status,
                # Content only after 完成/同步 so owners see synced submissions
                summary_text=row.summary_text if completed else None,
                next_actions=row.next_actions if completed else None,
                completed_at=row.completed_at if completed else None,
                updated_at=row.updated_at,
            )
        )
    return out


def _build_report(
    db: Session,
    *,
    project: Project,
    day: date,
    current_user: User,
    membership: TeamMember,
) -> DailyReportResponse:
    all_tasks = (
        db.query(Task)
        .filter(Task.project_id == project.id)
        .order_by(Task.sort_order.asc(), Task.created_at.asc())
        .all()
    )
    total = len(all_tasks)
    done = sum(1 for t in all_tasks if t.status == "done")
    progress = int(round((done / total) * 100)) if total else 0

    entries = (
        db.query(TaskTimeEntry)
        .filter(
            TaskTimeEntry.project_id == project.id,
            TaskTimeEntry.work_date == day,
        )
        .all()
    )
    entry_task_ids = {e.task_id for e in entries}
    hours_by_task: dict[uuid.UUID, float] = defaultdict(float)
    notes_by_task: dict[uuid.UUID, list[str]] = defaultdict(list)
    for entry in entries:
        hours_by_task[entry.task_id] += float(entry.hours or 0)
        if entry.note:
            notes_by_task[entry.task_id].append(entry.note)

    day_tasks_query = db.query(Task).filter(Task.project_id == project.id)
    if entry_task_ids:
        day_tasks_query = day_tasks_query.filter(
            or_(Task.due_date == day, Task.id.in_(entry_task_ids))
        )
    else:
        day_tasks_query = day_tasks_query.filter(Task.due_date == day)
    day_tasks = day_tasks_query.order_by(
        Task.sort_order.asc(), Task.created_at.asc()
    ).all()

    assignee_ids = {t.assignee_user_id for t in day_tasks if t.assignee_user_id}
    names: dict[uuid.UUID, str] = {}
    if assignee_ids:
        for user in db.query(User).filter(User.id.in_(assignee_ids)).all():
            names[user.id] = user.display_name or user.email or user.clerk_user_id

    work_items = [
        DailyReportWorkItem(
            task_id=task.id,
            title=task.title,
            status=task.status,
            assignee_user_id=task.assignee_user_id,
            assignee_display_name=(
                names.get(task.assignee_user_id) if task.assignee_user_id else None
            ),
            due_date=task.due_date,
            logged_hours=round(float(hours_by_task.get(task.id, 0.0)), 1),
            notes=notes_by_task.get(task.id, []),
        )
        for task in day_tasks
    ]
    day_hours = round(sum(hours_by_task.values()), 1)
    auto = _auto_summary(
        day=day,
        day_task_count=len(work_items),
        day_hours=day_hours,
        progress=progress,
        done=done,
        total=total,
    )

    saved = _get_own_report(
        db, project_id=project.id, day=day, user_id=current_user.id
    )
    can_view = _can_view_all(
        project=project, membership=membership, user=current_user
    )
    submissions = (
        _build_submissions(
            db, team_id=project.team_id, project_id=project.id, day=day
        )
        if can_view
        else []
    )

    return DailyReportResponse(
        view_date=day,
        project_id=project.id,
        team_id=project.team_id,
        project_name=project.name,
        project_status=project.status,
        progress_percent=progress,
        total_tasks=total,
        done_tasks=done,
        day_task_count=len(work_items),
        day_logged_hours=day_hours,
        auto_summary=auto,
        user_id=current_user.id,
        summary_text=saved.summary_text if saved else None,
        next_actions=saved.next_actions if saved else None,
        status=saved.status if saved else "draft",
        completed_at=saved.completed_at if saved else None,
        saved=saved is not None,
        can_view_all=can_view,
        submissions=submissions,
        work_items=work_items,
    )


def _upsert_own_report(
    db: Session,
    *,
    team_id: uuid.UUID,
    project: Project,
    day: date,
    current_user: User,
    summary: str | None,
    actions: str | None,
    complete: bool,
) -> ProjectDailyReport:
    row = _get_own_report(
        db, project_id=project.id, day=day, user_id=current_user.id
    )
    if row is None:
        row = ProjectDailyReport(
            team_id=team_id,
            project_id=project.id,
            user_id=current_user.id,
            report_date=day,
            summary_text=summary,
            next_actions=actions,
            status="draft",
            created_by_user_id=current_user.id,
        )
        db.add(row)
    else:
        row.summary_text = summary
        row.next_actions = actions

    if complete:
        row.status = "completed"
        row.completed_at = datetime.now(timezone.utc)
    return row


@router.get("", response_model=DailyReportResponse)
def get_daily_report(
    team_id: uuid.UUID,
    project_id: uuid.UUID,
    view_date: date | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DailyReportResponse:
    _, membership = require_team_membership(db, team_id=team_id, user=current_user)
    project = _require_project(db, team_id=team_id, project_id=project_id)
    day = view_date or date.today()
    return _build_report(
        db,
        project=project,
        day=day,
        current_user=current_user,
        membership=membership,
    )


@router.put("", response_model=DailyReportResponse)
def save_daily_report(
    team_id: uuid.UUID,
    project_id: uuid.UUID,
    body: DailyReportSaveRequest,
    view_date: date | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DailyReportResponse:
    """Save the current user's own draft report (does not notify)."""
    _, membership = require_team_membership(db, team_id=team_id, user=current_user)
    project = _require_project(db, team_id=team_id, project_id=project_id)
    day = view_date or date.today()

    summary = _normalize_text(body.summary_text)
    actions = _normalize_text(body.next_actions)

    row = _upsert_own_report(
        db,
        team_id=team_id,
        project=project,
        day=day,
        current_user=current_user,
        summary=summary,
        actions=actions,
        complete=False,
    )
    # Editing after sync returns to draft until 完成 again
    if row.status == "completed":
        row.status = "draft"
        row.completed_at = None

    db.commit()
    return _build_report(
        db,
        project=project,
        day=day,
        current_user=current_user,
        membership=membership,
    )


@router.post("/complete", response_model=DailyReportResponse)
def complete_daily_report(
    team_id: uuid.UUID,
    project_id: uuid.UUID,
    body: DailyReportSaveRequest,
    view_date: date | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DailyReportResponse:
    """完成并同步：mark own report completed so owners can see it."""
    _, membership = require_team_membership(db, team_id=team_id, user=current_user)
    project = _require_project(db, team_id=team_id, project_id=project_id)
    day = view_date or date.today()

    summary = _normalize_text(body.summary_text)
    actions = _normalize_text(body.next_actions)

    _upsert_own_report(
        db,
        team_id=team_id,
        project=project,
        day=day,
        current_user=current_user,
        summary=summary,
        actions=actions,
        complete=True,
    )

    author = (
        current_user.display_name
        or current_user.email
        or current_user.clerk_user_id
    )
    notify_report_viewers(
        db,
        team_id=team_id,
        project=project,
        type="daily_report_completed",
        category="日报",
        title="成员日报已同步",
        body=f"{author} 已完成「{project.name}」{day.month}月{day.day}日个人日报。",
        link_path=(
            f"/teams/{team_id}/projects/{project.id}/report"
            f"?view_date={day.isoformat()}"
        ),
        exclude_user_id=current_user.id,
    )
    db.commit()
    return _build_report(
        db,
        project=project,
        day=day,
        current_user=current_user,
        membership=membership,
    )
