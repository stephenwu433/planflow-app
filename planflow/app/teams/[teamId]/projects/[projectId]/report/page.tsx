"use client";

import { useAuth } from "@clerk/nextjs";
import Link from "next/link";
import { useParams } from "next/navigation";
import { FormEvent, useCallback, useEffect, useState } from "react";

import {
  completeDailyReport,
  getDailyReport,
  saveDailyReport,
  type DailyReport,
  type MemberDailyReportSubmission,
} from "@/lib/daily-report-api";
import { listMyTeams } from "@/lib/teams-api";
import { STATUS_LABELS, type TaskStatus } from "@/lib/tasks-api";
import { WorkbenchShell } from "@/components/WorkbenchShell";

function todayIso() {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function formatCnDate(iso: string) {
  const [, m, d] = iso.split("-");
  if (!m || !d) return iso;
  return `${Number(m)}月${Number(d)}日`;
}

function memberLabel(sub: MemberDailyReportSubmission) {
  return sub.display_name || sub.email || "成员";
}

function statusLabel(status: string) {
  if (status === "completed") return "已同步";
  if (status === "draft") return "撰写中";
  return "未提交";
}

export default function ProjectDailyReportPage() {
  const { isLoaded, isSignedIn, getToken } = useAuth();
  const params = useParams<{ teamId: string; projectId: string }>();
  const teamId = typeof params.teamId === "string" ? params.teamId : "";
  const projectId = typeof params.projectId === "string" ? params.projectId : "";

  const [viewDate, setViewDate] = useState(todayIso);
  const [report, setReport] = useState<DailyReport | null>(null);
  const [summary, setSummary] = useState("");
  const [nextActions, setNextActions] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [completing, setCompleting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedMsg, setSavedMsg] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setError(null);
    setSavedMsg(null);
    const token = await getToken();
    if (!token) {
      setError("拿不到登录 token。请重新登录。");
      return;
    }
    const teams = await listMyTeams(token);
    if (!teams.teams.some((t) => t.id === teamId)) {
      setError("你不是这个团队的成员。");
      setReport(null);
      return;
    }
    const payload = await getDailyReport(token, teamId, projectId, viewDate);
    setReport(payload);
    setSummary(payload.summary_text || payload.auto_summary);
    setNextActions(payload.next_actions || "");
  }, [getToken, teamId, projectId, viewDate]);

  useEffect(() => {
    if (!isLoaded || !isSignedIn || !teamId || !projectId) return;
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        await refresh();
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [isLoaded, isSignedIn, teamId, projectId, refresh]);

  async function onSave(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    setSavedMsg(null);
    try {
      const token = await getToken();
      if (!token) throw new Error("拿不到登录 token");
      const payload = await saveDailyReport(
        token,
        teamId,
        projectId,
        {
          summary_text: summary,
          next_actions: nextActions,
        },
        viewDate,
      );
      setReport(payload);
      setSummary(payload.summary_text || payload.auto_summary);
      setNextActions(payload.next_actions || "");
      setSavedMsg("已保存我的日报草稿。完成后请点「完成并同步」。");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  async function onComplete() {
    setCompleting(true);
    setError(null);
    setSavedMsg(null);
    try {
      const token = await getToken();
      if (!token) throw new Error("拿不到登录 token");
      const payload = await completeDailyReport(
        token,
        teamId,
        projectId,
        {
          summary_text: summary,
          next_actions: nextActions,
        },
        viewDate,
      );
      setReport(payload);
      setSummary(payload.summary_text || payload.auto_summary);
      setNextActions(payload.next_actions || "");
      setSavedMsg("已完成并同步。负责人可在下方查看成员日报。");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setCompleting(false);
    }
  }

  const completedCount =
    report?.submissions.filter((s) => s.status === "completed").length ?? 0;
  const submissionTotal = report?.submissions.length ?? 0;

  return (
    <WorkbenchShell
      teamId={teamId}
      projectId={projectId}
      projectName={report?.project_name}
    >
    <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col px-6 py-10">
      <p className="text-xs font-medium uppercase tracking-[0.16em] text-zinc-500">
        Daily Project Report
      </p>
      <h1 className="mt-1 text-2xl font-semibold tracking-tight text-zinc-900">
        {report?.project_name || "项目"} · 项目日报
      </h1>
      <p className="mt-2 text-sm leading-6 text-zinc-600">
        每个人写自己的进展摘要与下一步；点「完成并同步」后，负责人可查看所有人的日报。
      </p>

      {!isLoaded ? (
        <p className="mt-8 text-sm text-zinc-500">确认登录…</p>
      ) : !isSignedIn ? (
        <p className="mt-8 text-sm text-amber-800">
          请先{" "}
          <Link href="/sign-in" className="underline">
            登录
          </Link>
          。
        </p>
      ) : (
        <div className="mt-8 space-y-8">
          <label className="flex w-fit flex-col gap-1 text-xs text-zinc-500">
            查看日期
            <input
              type="date"
              value={viewDate}
              onChange={(e) => setViewDate(e.target.value)}
              className="rounded-md border border-zinc-300 px-3 py-2 text-sm text-zinc-900"
            />
          </label>

          {error ? (
            <p className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
              {error}
            </p>
          ) : null}
          {savedMsg ? (
            <p className="rounded-md border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-900">
              {savedMsg}
            </p>
          ) : null}

          {loading || !report ? (
            <p className="text-sm text-zinc-500">生成日报…</p>
          ) : (
            <>
              <section className="rounded-md bg-zinc-900 px-5 py-5 text-white">
                <p className="text-xs uppercase tracking-wide text-zinc-400">
                  {formatCnDate(report.view_date)} · 项目进展概况
                </p>
                <p className="mt-3 text-sm leading-6 text-zinc-100">
                  {report.auto_summary}
                </p>
                <div className="mt-5 flex flex-wrap items-end justify-between gap-3">
                  <p className="text-xs text-zinc-400">
                    当日任务 {report.day_task_count} · 已填工时{" "}
                    {report.day_logged_hours}h · 完成 {report.done_tasks}/
                    {report.total_tasks}
                    {report.status === "completed" ? " · 我的日报已同步" : ""}
                  </p>
                  <p className="text-3xl font-semibold tabular-nums">
                    {report.progress_percent}%
                  </p>
                </div>
              </section>

              <section>
                <h2 className="text-sm font-medium uppercase tracking-wide text-zinc-500">
                  当日任务
                </h2>
                {report.work_items.length === 0 ? (
                  <p className="mt-3 text-sm text-zinc-500">
                    当天没有项目任务日志。可去每日任务页添加或填工时。
                  </p>
                ) : (
                  <ul className="mt-3 divide-y divide-zinc-200 border-t border-b border-zinc-200">
                    {report.work_items.map((item) => (
                      <li
                        key={item.task_id}
                        className="flex flex-col gap-1 py-3 sm:flex-row sm:items-center sm:justify-between"
                      >
                        <div className="min-w-0">
                          <p className="text-sm font-medium text-zinc-900">
                            {item.title}
                          </p>
                          <p className="text-xs text-zinc-500">
                            {item.assignee_display_name || "未指派"} ·{" "}
                            {STATUS_LABELS[item.status as TaskStatus] || item.status}
                            {item.notes.length
                              ? ` · ${item.notes.join("；")}`
                              : ""}
                          </p>
                        </div>
                        <p className="shrink-0 text-sm tabular-nums text-zinc-700">
                          {item.logged_hours}h
                        </p>
                      </li>
                    ))}
                  </ul>
                )}
              </section>

              <form onSubmit={onSave} className="space-y-4">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <h2 className="text-sm font-medium uppercase tracking-wide text-zinc-500">
                    我的日报
                  </h2>
                  <p className="text-xs text-zinc-500">
                    状态：{statusLabel(report.status)}
                  </p>
                </div>
                <label className="flex flex-col gap-1 text-xs text-zinc-500">
                  进展摘要
                  <textarea
                    value={summary}
                    onChange={(e) => setSummary(e.target.value)}
                    rows={4}
                    maxLength={4000}
                    className="rounded-md border border-zinc-300 px-3 py-2 text-sm text-zinc-900 outline-none focus:border-zinc-500"
                  />
                </label>
                <label className="flex flex-col gap-1 text-xs text-zinc-500">
                  下一步（每行一条）
                  <textarea
                    value={nextActions}
                    onChange={(e) => setNextActions(e.target.value)}
                    rows={4}
                    maxLength={4000}
                    placeholder={"1. 完成接口联调\n2. 同步风险给负责人"}
                    className="rounded-md border border-zinc-300 px-3 py-2 text-sm text-zinc-900 outline-none focus:border-zinc-500"
                  />
                </label>
                {nextActions.trim() ? (
                  <div>
                    <p className="text-xs font-medium uppercase tracking-wide text-zinc-500">
                      下一步预览
                    </p>
                    <ol className="mt-2 list-decimal space-y-1 pl-5 text-sm text-zinc-800">
                      {nextActions
                        .split("\n")
                        .map((line) => line.trim())
                        .filter(Boolean)
                        .map((line) => (
                          <li key={line}>{line.replace(/^\d+[\.\、]\s*/, "")}</li>
                        ))}
                    </ol>
                  </div>
                ) : null}
                <div className="flex flex-wrap gap-3">
                  <button
                    type="submit"
                    disabled={saving || completing}
                    className="rounded-md border border-zinc-300 bg-white px-4 py-2 text-sm font-medium text-zinc-900 hover:bg-zinc-50 disabled:opacity-50"
                  >
                    {saving ? "保存中…" : "保存草稿"}
                  </button>
                  <button
                    type="button"
                    onClick={onComplete}
                    disabled={saving || completing}
                    className="rounded-md bg-zinc-900 px-4 py-2 text-sm font-medium text-white hover:bg-zinc-800 disabled:opacity-50"
                  >
                    {completing ? "同步中…" : "完成并同步"}
                  </button>
                </div>
              </form>

              {report.can_view_all ? (
                <section className="space-y-4">
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <h2 className="text-sm font-medium uppercase tracking-wide text-zinc-500">
                      成员日报（同步后可见内容）
                    </h2>
                    <p className="text-xs text-zinc-500">
                      已同步 {completedCount}/{submissionTotal}
                    </p>
                  </div>
                  {report.submissions.length === 0 ? (
                    <p className="text-sm text-zinc-500">暂无团队成员。</p>
                  ) : (
                    <ul className="divide-y divide-zinc-200 border-t border-b border-zinc-200">
                      {report.submissions.map((sub) => (
                        <li key={sub.user_id} className="space-y-2 py-4">
                          <div className="flex flex-wrap items-baseline justify-between gap-2">
                            <p className="text-sm font-medium text-zinc-900">
                              {memberLabel(sub)}
                              {sub.user_id === report.user_id ? "（我）" : ""}
                            </p>
                            <p className="text-xs text-zinc-500">
                              {statusLabel(sub.status)}
                            </p>
                          </div>
                          {sub.status === "completed" ? (
                            <div className="space-y-2 text-sm text-zinc-700">
                              <p className="leading-6 whitespace-pre-wrap">
                                {sub.summary_text || "（无进展摘要）"}
                              </p>
                              {sub.next_actions?.trim() ? (
                                <ol className="list-decimal space-y-1 pl-5 text-zinc-800">
                                  {sub.next_actions
                                    .split("\n")
                                    .map((line) => line.trim())
                                    .filter(Boolean)
                                    .map((line) => (
                                      <li key={line}>
                                        {line.replace(/^\d+[\.\、]\s*/, "")}
                                      </li>
                                    ))}
                                </ol>
                              ) : null}
                            </div>
                          ) : (
                            <p className="text-sm text-zinc-500">
                              {sub.status === "draft"
                                ? "成员仍在撰写，完成同步后内容会出现在这里。"
                                : "尚未提交个人日报。"}
                            </p>
                          )}
                        </li>
                      ))}
                    </ul>
                  )}
                </section>
              ) : null}
            </>
          )}
        </div>
      )}
    </main>
    </WorkbenchShell>
  );
}
