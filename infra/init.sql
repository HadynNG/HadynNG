-- =============================================================================
-- HadynNG — PostgreSQL schema initialisation
-- =============================================================================

-- ── Missions ────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS missions (
    id              TEXT PRIMARY KEY,
    customer_id     TEXT NOT NULL,
    customer_name   TEXT NOT NULL,
    event_type      TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'PENDING',
    model           TEXT,
    plan            JSONB,
    context         JSONB DEFAULT '{}'::jsonb,
    final_decision  TEXT,
    risk_level      TEXT,
    risk_score      REAL,
    screening_hits  INTEGER DEFAULT 0,
    edd_required    BOOLEAN DEFAULT FALSE,
    str_filed       BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_missions_customer ON missions (customer_id);
CREATE INDEX IF NOT EXISTS idx_missions_status ON missions (status);
CREATE INDEX IF NOT EXISTS idx_missions_created ON missions (created_at DESC);

-- ── Audit Logs (append-only, AMLO 5-year retention) ────────────────────────

CREATE TABLE IF NOT EXISTS audit_logs (
    id              BIGSERIAL PRIMARY KEY,
    mission_id      TEXT NOT NULL REFERENCES missions(id),
    agent           TEXT NOT NULL,
    level           TEXT NOT NULL DEFAULT 'INFO',
    message         TEXT NOT NULL,
    metadata        JSONB DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_mission ON audit_logs (mission_id);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_logs (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_agent ON audit_logs (agent);

-- Prevent UPDATE/DELETE on audit_logs (WORM compliance)
CREATE OR REPLACE FUNCTION prevent_audit_modification()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'Audit log records cannot be modified or deleted (AMLO compliance)';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_audit_no_update ON audit_logs;
CREATE TRIGGER trg_audit_no_update
    BEFORE UPDATE OR DELETE ON audit_logs
    FOR EACH ROW EXECUTE FUNCTION prevent_audit_modification();

-- ── Mission Timeline Phases ────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS mission_phases (
    id              BIGSERIAL PRIMARY KEY,
    mission_id      TEXT NOT NULL REFERENCES missions(id),
    sequence        INTEGER NOT NULL,
    phase_id        TEXT NOT NULL,
    label           TEXT NOT NULL,
    agent           TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'PENDING',
    summary         TEXT,
    key_outputs     JSONB DEFAULT '{}'::jsonb,
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    duration_secs   REAL
);

CREATE INDEX IF NOT EXISTS idx_phases_mission ON mission_phases (mission_id);

-- ── User Preferences (for memory service) ──────────────────────────────────

CREATE TABLE IF NOT EXISTS user_preferences (
    id              BIGSERIAL PRIMARY KEY,
    user_id         TEXT NOT NULL,
    key             TEXT NOT NULL,
    value           JSONB NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, key)
);

CREATE INDEX IF NOT EXISTS idx_prefs_user ON user_preferences (user_id);

-- ── Customer Records (production CRM cache) ────────────────────────────────

CREATE TABLE IF NOT EXISTS customers (
    customer_id     TEXT PRIMARY KEY,
    full_name       TEXT NOT NULL,
    aliases         JSONB DEFAULT '[]'::jsonb,
    date_of_birth   TEXT,
    nationality     TEXT,
    id_type         TEXT,
    id_number       TEXT,
    address         TEXT,
    email           TEXT,
    phone           TEXT,
    customer_type   TEXT DEFAULT 'individual',
    occupation      TEXT,
    employer        TEXT,
    jurisdiction    TEXT,
    pep_self_declared BOOLEAN DEFAULT FALSE,
    existing_risk_rating TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_customers_name ON customers USING gin (to_tsvector('english', full_name));

-- ── Screening Results (historical) ─────────────────────────────────────────

CREATE TABLE IF NOT EXISTS screening_results (
    id              BIGSERIAL PRIMARY KEY,
    mission_id      TEXT NOT NULL REFERENCES missions(id),
    customer_id     TEXT NOT NULL,
    query_name      TEXT NOT NULL,
    hit_name        TEXT,
    list_type       TEXT,
    confidence      REAL,
    disposition     TEXT,  -- TRUE_POSITIVE, FALSE_POSITIVE, PENDING
    metadata        JSONB DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_screening_mission ON screening_results (mission_id);
CREATE INDEX IF NOT EXISTS idx_screening_customer ON screening_results (customer_id);
