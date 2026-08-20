-- Baseline schema for PostgreSQL deployments. The application creates the same
-- development schema on startup; production changes should be appended here.
CREATE TABLE IF NOT EXISTS users (
  id varchar(36) PRIMARY KEY, email varchar(320) UNIQUE NOT NULL,
  password_hash varchar(128) NOT NULL, tenant_id varchar(36) NOT NULL,
  created_at timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_users_email ON users(email);
CREATE TABLE IF NOT EXISTS widgets (
  id varchar(36) PRIMARY KEY, tenant_id varchar(36) NOT NULL, name varchar(100) NOT NULL,
  widget_type varchar(20) NOT NULL, title varchar(160) NOT NULL, description text,
  button_text varchar(60) NOT NULL, fields jsonb NOT NULL, allowed_origins jsonb NOT NULL,
  active boolean NOT NULL DEFAULT true, created_at timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_widgets_tenant_id ON widgets(tenant_id);
CREATE TABLE IF NOT EXISTS submissions (
  id varchar(36) PRIMARY KEY, tenant_id varchar(36) NOT NULL,
  widget_id varchar(36) NOT NULL REFERENCES widgets(id), idempotency_key varchar(128) NOT NULL,
  payload jsonb NOT NULL, ip_address varchar(64), geo jsonb, notification_status varchar(32) NOT NULL,
  created_at timestamptz DEFAULT now(), CONSTRAINT uq_submission_widget_key UNIQUE(widget_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS ix_submissions_tenant_id ON submissions(tenant_id);
CREATE INDEX IF NOT EXISTS ix_submissions_widget_id ON submissions(widget_id);
