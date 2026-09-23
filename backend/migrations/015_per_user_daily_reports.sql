-- Per-user project daily reports: each member writes their own for a date.
-- Owners/admins can see completed submissions after 完成/同步.

ALTER TABLE project_daily_reports
    ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users (id) ON DELETE CASCADE;

UPDATE project_daily_reports
SET user_id = created_by_user_id
WHERE user_id IS NULL;

-- Deduplicate any legacy rows that would collide after adding user_id
-- (should be rare: old unique was project_id + report_date).
DELETE FROM project_daily_reports a
USING project_daily_reports b
WHERE a.user_id IS NOT NULL
  AND b.user_id IS NOT NULL
  AND a.project_id = b.project_id
  AND a.report_date = b.report_date
  AND a.user_id = b.user_id
  AND a.ctid < b.ctid;

ALTER TABLE project_daily_reports
    ALTER COLUMN user_id SET NOT NULL;

ALTER TABLE project_daily_reports
    ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'draft';

ALTER TABLE project_daily_reports
    DROP CONSTRAINT IF EXISTS chk_project_daily_reports_status;
ALTER TABLE project_daily_reports
    ADD CONSTRAINT chk_project_daily_reports_status
    CHECK (status IN ('draft', 'completed'));

ALTER TABLE project_daily_reports
    ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ;

ALTER TABLE project_daily_reports
    DROP CONSTRAINT IF EXISTS uq_project_daily_reports_project_date;

ALTER TABLE project_daily_reports
    DROP CONSTRAINT IF EXISTS uq_project_daily_reports_project_date_user;
ALTER TABLE project_daily_reports
    ADD CONSTRAINT uq_project_daily_reports_project_date_user
    UNIQUE (project_id, report_date, user_id);

CREATE INDEX IF NOT EXISTS idx_project_daily_reports_project_date_user
    ON project_daily_reports (project_id, report_date, user_id);
