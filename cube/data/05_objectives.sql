-- CPGAN-13 / CPGAN-15: Persona objective definitions, data-driven by role.
-- New role/template = new rows only, no code change required.

CREATE TABLE IF NOT EXISTS app_meta.objective_templates (
  template_id   VARCHAR(64) PRIMARY KEY,
  role          VARCHAR(32) NOT NULL,
  title         VARCHAR(160) NOT NULL,
  description   TEXT,
  order_no      INTEGER NOT NULL DEFAULT 0,
  is_active     BOOLEAN NOT NULL DEFAULT TRUE,
  created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS app_meta.template_questions (
  question_id   VARCHAR(64) PRIMARY KEY,
  template_id   VARCHAR(64) NOT NULL REFERENCES app_meta.objective_templates(template_id),
  question_text TEXT NOT NULL,
  input_type    VARCHAR(16) NOT NULL DEFAULT 'single_select',
  order_no      INTEGER NOT NULL DEFAULT 0,
  is_required   BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS app_meta.question_options (
  option_id     VARCHAR(64) PRIMARY KEY,
  question_id   VARCHAR(64) NOT NULL REFERENCES app_meta.template_questions(question_id),
  label         VARCHAR(160) NOT NULL,
  value         VARCHAR(160) NOT NULL,
  order_no      INTEGER NOT NULL DEFAULT 0
);

ALTER TABLE app_meta.chat_sessions
  ADD COLUMN IF NOT EXISTS template_id VARCHAR(64) REFERENCES app_meta.objective_templates(template_id),
  ADD COLUMN IF NOT EXISTS objective_answers JSONB;

CREATE INDEX IF NOT EXISTS idx_objective_templates_role ON app_meta.objective_templates(role);
CREATE INDEX IF NOT EXISTS idx_template_questions_template ON app_meta.template_questions(template_id);
CREATE INDEX IF NOT EXISTS idx_question_options_question ON app_meta.question_options(question_id);

-- Templates: all six roles
INSERT INTO app_meta.objective_templates (template_id, role, title, description, order_no) VALUES
  ('tmpl_so_daily',      'SO',      'Daily Field Review',     'Track your territory performance day to day',       1),
  ('tmpl_asm_zone',      'ASM',     'Zone Performance Watch', 'Monitor your zone vs targets',                      1),
  ('tmpl_zsm_region',    'ZSM',     'Regional Risk & Growth', 'Spot anomalies and growth across your region',      1),
  ('tmpl_nsm_national',  'NSM',     'National Sales Pulse',   'High-level KPI tracking across all zones',          1),
  ('tmpl_admin_overview','admin',   'Platform Overview',      'Monitor all tenants and system health',             1),
  ('tmpl_analyst_deep',  'analyst', 'Deep Dive Analysis',     'Explore sales data across dimensions',              1)
ON CONFLICT (template_id) DO NOTHING;

-- Questions
INSERT INTO app_meta.template_questions (question_id, template_id, question_text, input_type, order_no) VALUES
  ('q_so_metric',      'tmpl_so_daily',       'Which metric matters most to you?', 'single_select', 1),
  ('q_so_window',      'tmpl_so_daily',       'What time window?',                 'single_select', 2),
  ('q_asm_metric',     'tmpl_asm_zone',       'Which metric matters most to you?', 'single_select', 1),
  ('q_asm_window',     'tmpl_asm_zone',       'What time window?',                 'single_select', 2),
  ('q_admin_focus',    'tmpl_admin_overview', 'What do you want to monitor?',      'single_select', 1),
  ('q_analyst_metric', 'tmpl_analyst_deep',   'Which metric to deep dive?',        'single_select', 1)
ON CONFLICT (question_id) DO NOTHING;

-- Options
INSERT INTO app_meta.question_options (option_id, question_id, label, value, order_no) VALUES
  ('opt_so_m1',  'q_so_metric',      'Net Sales',        'net_sales',        1),
  ('opt_so_m2',  'q_so_metric',      'Outlet Coverage',  'outlet_coverage',  2),
  ('opt_so_w1',  'q_so_window',      'Today',            'today',            1),
  ('opt_so_w2',  'q_so_window',      'Last 7 days',      'last_7d',          2),
  ('opt_asm_m1', 'q_asm_metric',     'Net Sales',        'net_sales',        1),
  ('opt_asm_m2', 'q_asm_metric',     'Target vs Actual', 'target_vs_actual', 2),
  ('opt_asm_w1', 'q_asm_window',     'This week',        'this_week',        1),
  ('opt_asm_w2', 'q_asm_window',     'MTD',              'mtd',              2),
  ('opt_adm_1',  'q_admin_focus',    'All Tenants',      'all_tenants',      1),
  ('opt_adm_2',  'q_admin_focus',    'System Health',    'system_health',    2),
  ('opt_ana_1',  'q_analyst_metric', 'Net Sales',        'net_sales',        1),
  ('opt_ana_2',  'q_analyst_metric', 'Returns %',        'returns_pct',      2)
ON CONFLICT (option_id) DO NOTHING;
