/**
 * Shared display helpers for assignee selects (schedule / tasks).
 * Prefer human-readable names over raw user ids.
 */

import { jobTitleLabel } from "./members-api";

export type AssigneeOption = {
  user_id: string;
  display_name: string | null;
  email: string | null;
  clerk_user_id?: string | null;
  job_title?: string | null;
};

export function assigneeDisplayName(m: AssigneeOption): string {
  const name = m.display_name?.trim();
  if (name) return name;
  const email = m.email?.trim();
  if (email) return email;
  const clerk = m.clerk_user_id?.trim();
  if (clerk) return clerk;
  return `成员 ${m.user_id.slice(0, 8)}`;
}

export function assigneeOptionLabel(m: AssigneeOption): string {
  const name = assigneeDisplayName(m);
  if (!m.job_title) return name;
  const job = jobTitleLabel(m.job_title);
  if (!job || job === "未设置岗位") return name;
  return `${name}（${job}）`;
}

export function assigneeLabelForId(
  userId: string | null,
  members: AssigneeOption[],
): string {
  if (!userId) return "未指派";
  const m = members.find((x) => x.user_id === userId);
  if (!m) return `未知成员（${userId.slice(0, 8)}）`;
  return assigneeOptionLabel(m);
}
