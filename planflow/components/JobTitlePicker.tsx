"use client";

import { FormEvent, useEffect, useState } from "react";

import {
  CUSTOM_JOB_TITLE_VALUE,
  JOB_TITLE_LABELS,
  JOB_TITLE_MAX_LENGTH,
  JOB_TITLE_PRESET_KEYS,
  isPresetJobTitle,
  jobTitleSelectValue,
  type JobTitle,
} from "@/lib/members-api";

type JobTitlePickerProps = {
  value: string | null | undefined;
  disabled?: boolean;
  emptyLabel?: string;
  className?: string;
  selectClassName?: string;
  onSave: (jobTitle: string | null) => void | Promise<void>;
};

/**
 * Preset dropdown + optional free-text custom job title.
 * Selecting「自定义…」reveals an input; saving persists the typed label.
 */
export function JobTitlePicker({
  value,
  disabled = false,
  emptyLabel = "未设置岗位",
  className = "",
  selectClassName = "rounded-md border border-zinc-300 px-2 py-1 text-xs",
  onSave,
}: JobTitlePickerProps) {
  const isCustom = !!value && !isPresetJobTitle(value);
  const [showCustom, setShowCustom] = useState(isCustom);
  const [draft, setDraft] = useState(isCustom ? value || "" : "");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const custom = !!value && !isPresetJobTitle(value);
    setShowCustom(custom);
    setDraft(custom ? value || "" : "");
  }, [value]);

  async function persist(next: string | null) {
    setBusy(true);
    try {
      await onSave(next);
    } finally {
      setBusy(false);
    }
  }

  async function onSelectChange(raw: string) {
    if (raw === CUSTOM_JOB_TITLE_VALUE) {
      setShowCustom(true);
      setDraft(isCustom ? value || "" : "");
      return;
    }
    setShowCustom(false);
    setDraft("");
    await persist(raw || null);
  }

  async function onSubmitCustom(e: FormEvent) {
    e.preventDefault();
    const trimmed = draft.trim();
    if (!trimmed) return;
    await persist(trimmed);
  }

  return (
    <div className={`flex flex-col items-stretch gap-1 sm:items-end ${className}`}>
      <select
        value={showCustom ? CUSTOM_JOB_TITLE_VALUE : jobTitleSelectValue(value)}
        disabled={disabled || busy}
        onChange={(e) => void onSelectChange(e.target.value)}
        className={selectClassName}
      >
        <option value="">{emptyLabel}</option>
        {JOB_TITLE_PRESET_KEYS.map((key) => (
          <option key={key} value={key}>
            {JOB_TITLE_LABELS[key as JobTitle]}
          </option>
        ))}
        <option value={CUSTOM_JOB_TITLE_VALUE}>自定义…</option>
      </select>
      {showCustom ? (
        <form
          onSubmit={(e) => void onSubmitCustom(e)}
          className="flex items-center gap-1"
        >
          <input
            value={draft}
            disabled={disabled || busy}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="输入岗位名称"
            maxLength={JOB_TITLE_MAX_LENGTH}
            className="min-w-[8rem] rounded-md border border-zinc-300 px-2 py-1 text-xs outline-none focus:border-zinc-500"
            autoFocus={!isCustom}
          />
          <button
            type="submit"
            disabled={disabled || busy || !draft.trim()}
            className="rounded-md bg-zinc-900 px-2 py-1 text-xs text-white disabled:opacity-50"
          >
            保存
          </button>
        </form>
      ) : null}
    </div>
  );
}
