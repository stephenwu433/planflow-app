"""Job title presets + free-text custom titles."""

from __future__ import annotations

from fastapi import HTTPException

from app.schemas import JOB_TITLE_LABELS_ZH, JOB_TITLES

# Max length aligns with TeamMemberUpdateRequest / ProjectMember* schemas.
MAX_JOB_TITLE_LENGTH = 40

# Chinese preset labels (and common aliases) → stored preset keys.
_JOB_TITLE_ALIASES: dict[str, str] = {
    **{label: key for key, label in JOB_TITLE_LABELS_ZH.items()},
    "产品": "pm",
    "设计": "designer",
    "运营同学": "ops",
}


def is_preset_job_title(job: str | None) -> bool:
    return bool(job) and job in JOB_TITLES


def job_title_label(job: str | None) -> str | None:
    """Chinese label for presets; raw string for custom titles."""
    if not job:
        return None
    return JOB_TITLE_LABELS_ZH.get(job, job)


def normalize_job_title(raw: str | None, *, max_length: int = MAX_JOB_TITLE_LENGTH) -> str | None:
    """Normalize incoming job title.

    Preset keys (and Chinese preset labels) map to canonical keys.
    Anything else is accepted as a free-text custom title (trimmed).
    """
    if raw is None:
        return None
    value = raw.strip()
    if not value:
        return None
    if len(value) > max_length:
        raise HTTPException(
            status_code=400,
            detail=f"job_title must be at most {max_length} characters",
        )

    lower = value.lower()
    if lower in JOB_TITLES:
        return lower

    alias = _JOB_TITLE_ALIASES.get(value) or _JOB_TITLE_ALIASES.get(lower)
    if alias is not None:
        return alias

    # Custom free-text title — keep user-facing casing.
    return value


def coerce_suggested_job(raw: str | None, *, available_jobs: list[str]) -> str | None:
    """Map an AI/suggested job onto a usable title in available_jobs.

    Accepts presets and custom titles present on the roster. Unknown values
    fall back to ``other`` when available, else None.
    """
    if raw is None:
        return None
    value = str(raw).strip()
    if not value:
        return None
    if len(value) > MAX_JOB_TITLE_LENGTH:
        value = value[:MAX_JOB_TITLE_LENGTH].rstrip()

    available = [j for j in available_jobs if j]
    available_lower = {j.lower(): j for j in available}

    lower = value.lower()
    if lower in JOB_TITLES:
        normalized: str | None = lower
    else:
        alias = _JOB_TITLE_ALIASES.get(value) or _JOB_TITLE_ALIASES.get(lower)
        normalized = alias if alias is not None else value

    if normalized in available:
        return normalized
    if normalized.lower() in available_lower:
        return available_lower[normalized.lower()]

    if value in available:
        return value
    if value.lower() in available_lower:
        return available_lower[value.lower()]

    if "other" in available:
        return "other"
    if available:
        return available[0]
    return None
