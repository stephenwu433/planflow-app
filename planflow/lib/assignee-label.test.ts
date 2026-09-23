/**
 * Unit checks for assignee display helpers (no test runner required).
 * Run: npx tsx lib/assignee-label.test.ts
 */

import {
  assigneeDisplayName,
  assigneeLabelForId,
  assigneeOptionLabel,
} from "./assignee-label";

function assert(cond: unknown, msg: string) {
  if (!cond) throw new Error(msg);
}

const tongtong = {
  user_id: "uuid-tt",
  display_name: "桶桶",
  email: "tt@example.com",
  clerk_user_id: "clerk_tt",
  job_title: "pm" as const,
};

const nameless = {
  user_id: "00000000-0000-0000-0000-000000000001",
  display_name: null,
  email: null,
  clerk_user_id: "clerk_x",
  job_title: null,
};

assert(assigneeDisplayName(tongtong) === "桶桶", "prefer display_name");
assert(assigneeOptionLabel(tongtong) === "桶桶（产品经理）", "name + job");
assert(assigneeDisplayName(nameless) === "clerk_x", "fallback clerk id");
assert(
  assigneeLabelForId("uuid-tt", [tongtong, nameless]) === "桶桶（产品经理）",
  "lookup by id",
);
assert(
  assigneeLabelForId("missing-id-abcdef12", [tongtong]) ===
    "未知成员（missing-）",
  "unknown member",
);
assert(assigneeLabelForId(null, [tongtong]) === "未指派", "null assignee");
assert(
  assigneeLabelForId("0", []) === "未知成员（0）",
  "numeric-looking orphan id",
);
assert(
  assigneeLabelForId("1", []) === "未知成员（1）",
  "numeric-looking orphan id 1",
);

console.log("assignee-label tests OK");
