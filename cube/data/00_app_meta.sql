CREATE SCHEMA IF NOT EXISTS app_meta;
CREATE SCHEMA IF NOT EXISTS client_nestle;
CREATE SCHEMA IF NOT EXISTS client_itc;
CREATE SCHEMA IF NOT EXISTS client_unilever;

CREATE TABLE IF NOT EXISTS app_meta.clients (
  client_id VARCHAR(64) PRIMARY KEY,
  client_name VARCHAR(160) NOT NULL,
  schema_name VARCHAR(128) NOT NULL UNIQUE,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS app_meta.users (
  user_id BIGSERIAL PRIMARY KEY,
  username VARCHAR(80) UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  email VARCHAR(160) UNIQUE NOT NULL,
  full_name VARCHAR(160) NOT NULL,
  client_id VARCHAR(64) NOT NULL REFERENCES app_meta.clients(client_id),
  role VARCHAR(32) NOT NULL,
  department VARCHAR(80) NOT NULL DEFAULT 'analytics',
  sales_hierarchy_level VARCHAR(16),
  salesrep_code VARCHAR(64),
  so_code VARCHAR(64),
  asm_code VARCHAR(64),
  zsm_code VARCHAR(64),
  nsm_code VARCHAR(64),
  territory_codes TEXT,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_login TIMESTAMP
);

CREATE TABLE IF NOT EXISTS app_meta.audit_log (
  log_id BIGSERIAL PRIMARY KEY,
  user_id BIGINT REFERENCES app_meta.users(user_id),
  username VARCHAR(80) NOT NULL,
  client_id VARCHAR(64) NOT NULL,
  question TEXT NOT NULL,
  cube_query JSONB,
  success BOOLEAN NOT NULL,
  error_message TEXT,
  duration_ms INTEGER,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS app_meta.chat_sessions (
  session_id VARCHAR(80) PRIMARY KEY,
  user_id BIGINT NOT NULL REFERENCES app_meta.users(user_id),
  client_id VARCHAR(64) NOT NULL,
  title VARCHAR(200) NOT NULL DEFAULT 'New conversation',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_active TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  is_active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS app_meta.chat_messages (
  message_id VARCHAR(80) PRIMARY KEY,
  session_id VARCHAR(80) NOT NULL REFERENCES app_meta.chat_sessions(session_id),
  user_id BIGINT NOT NULL REFERENCES app_meta.users(user_id),
  role VARCHAR(16) NOT NULL,
  content TEXT NOT NULL,
  raw_data JSONB,
  query_type VARCHAR(40),
  metadata JSONB,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS app_meta.insights (
  insight_id VARCHAR(160) PRIMARY KEY,
  tenant_id VARCHAR(64) NOT NULL,
  hierarchy_level VARCHAR(16) NOT NULL,
  salesrep_code VARCHAR(64),
  so_code VARCHAR(64),
  asm_code VARCHAR(64),
  zsm_code VARCHAR(64),
  nsm_code VARCHAR(64),
  title TEXT NOT NULL,
  description TEXT NOT NULL,
  insight_type VARCHAR(40) NOT NULL,
  priority VARCHAR(16) NOT NULL,
  metric_value NUMERIC,
  metric_change_pct NUMERIC,
  suggested_action TEXT,
  suggested_query TEXT,
  data_json JSONB,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  expires_at TIMESTAMP,
  is_active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS app_meta.insight_reads (
  id BIGSERIAL PRIMARY KEY,
  insight_id VARCHAR(160) NOT NULL REFERENCES app_meta.insights(insight_id),
  user_id BIGINT NOT NULL REFERENCES app_meta.users(user_id),
  read_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(insight_id, user_id)
);

INSERT INTO app_meta.clients (client_id, client_name, schema_name) VALUES
  ('nestle', 'Nestle India', 'client_nestle'),
  ('itc', 'ITC Limited', 'client_itc'),
  ('unilever', 'Unilever India', 'client_unilever')
ON CONFLICT (client_id) DO UPDATE SET
  client_name = EXCLUDED.client_name,
  schema_name = EXCLUDED.schema_name,
  is_active = TRUE;

INSERT INTO app_meta.users
  (username, password_hash, email, full_name, client_id, role, department,
   sales_hierarchy_level, salesrep_code, so_code, asm_code, zsm_code, nsm_code)
VALUES
  ('nestle_admin', 'plain:admin123', 'admin@nestle.example', 'Nestle Admin', 'nestle', 'admin', 'analytics', NULL, NULL, NULL, NULL, NULL, NULL),
  ('nestle_analyst', 'plain:analyst123', 'analyst@nestle.example', 'Nestle Analyst', 'nestle', 'analyst', 'analytics', NULL, NULL, NULL, NULL, NULL, NULL),
  ('nsm_rajesh', 'plain:nsm123', 'rajesh@nestle.example', 'Rajesh Kumar', 'nestle', 'NSM', 'sales', 'NSM', NULL, NULL, NULL, NULL, 'NSM01'),
  ('zsm_amit', 'plain:zsm123', 'amit@nestle.example', 'Amit Shah', 'nestle', 'ZSM', 'sales', 'ZSM', NULL, NULL, NULL, 'ZSM-01', NULL),
  ('asm_rahul', 'plain:asm123', 'rahul@nestle.example', 'Rahul Verma', 'nestle', 'ASM', 'sales', 'ASM', NULL, NULL, 'ASM-01', NULL, NULL),
  ('so_field1', 'plain:so123', 'field1@nestle.example', 'Field Officer 1', 'nestle', 'SO', 'sales', 'SO', 'SR001', 'SO-01', NULL, NULL, NULL),
  ('itc_admin', 'plain:admin123', 'admin@itc.example', 'ITC Admin', 'itc', 'admin', 'analytics', NULL, NULL, NULL, NULL, NULL, NULL),
  ('unilever_admin', 'plain:admin123', 'admin@unilever.example', 'Unilever Admin', 'unilever', 'admin', 'analytics', NULL, NULL, NULL, NULL, NULL, NULL)
ON CONFLICT (username) DO UPDATE SET
  password_hash = EXCLUDED.password_hash,
  email = EXCLUDED.email,
  full_name = EXCLUDED.full_name,
  client_id = EXCLUDED.client_id,
  role = EXCLUDED.role,
  department = EXCLUDED.department,
  sales_hierarchy_level = EXCLUDED.sales_hierarchy_level,
  salesrep_code = EXCLUDED.salesrep_code,
  so_code = EXCLUDED.so_code,
  asm_code = EXCLUDED.asm_code,
  zsm_code = EXCLUDED.zsm_code,
  nsm_code = EXCLUDED.nsm_code,
  is_active = TRUE;
