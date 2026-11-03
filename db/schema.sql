CREATE TABLE IF NOT EXISTS filters (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT    NOT NULL,
    filter_type   TEXT    NOT NULL CHECK (filter_type IN ('standard', 'counting')),
    n_capacity    INTEGER NOT NULL CHECK (n_capacity >= 1),
    target_fp     REAL    NOT NULL CHECK (target_fp > 0 AND target_fp < 1),
    m_bits        INTEGER NOT NULL CHECK (m_bits >= 1),
    k_hashes      INTEGER NOT NULL CHECK (k_hashes >= 1),
    item_count    INTEGER NOT NULL DEFAULT 0,
    is_active     INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    state_file    TEXT    NOT NULL,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_filters_one_active
    ON filters (is_active) WHERE is_active = 1;

CREATE TABLE IF NOT EXISTS blacklist_entries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    filter_id   INTEGER NOT NULL REFERENCES filters(id) ON DELETE CASCADE,
    item_raw    TEXT    NOT NULL,
    item_key    TEXT    NOT NULL,
    key_type    TEXT    NOT NULL CHECK (key_type IN
                    ('transaction_id', 'email', 'url', 'ip', 'phone', 'other')),
    label       TEXT    NOT NULL DEFAULT 'fraud' CHECK (label IN
                    ('fraud', 'spam', 'phishing', 'other')),
    source      TEXT    NOT NULL DEFAULT 'manual',
    added_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (filter_id, item_key)
);
CREATE INDEX IF NOT EXISTS ix_blacklist_type_label ON blacklist_entries (key_type, label);

CREATE TABLE IF NOT EXISTS check_logs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    filter_id     INTEGER REFERENCES filters(id) ON DELETE SET NULL,
    item_key      TEXT    NOT NULL,
    key_type      TEXT    NOT NULL,
    mode          TEXT    NOT NULL CHECK (mode IN ('two_stage', 'bloom_only')),
    bloom_result  TEXT    NOT NULL CHECK (bloom_result IN ('ABSENT', 'PROBABLE')),
    exact_result  TEXT             CHECK (exact_result IN ('FOUND', 'NOT_FOUND')),
    verdict       TEXT    NOT NULL CHECK (verdict IN
                    ('CLEAN', 'BLACKLISTED', 'FALSE_POSITIVE', 'POSSIBLY_BLACKLISTED')),
    latency_us    INTEGER NOT NULL,
    checked_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_logs_time    ON check_logs (checked_at DESC);
CREATE INDEX IF NOT EXISTS ix_logs_verdict ON check_logs (verdict);

CREATE TABLE IF NOT EXISTS import_jobs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    filter_id       INTEGER REFERENCES filters(id) ON DELETE SET NULL,
    source          TEXT    NOT NULL,
    file_name       TEXT,
    rows_read       INTEGER NOT NULL,
    rows_added      INTEGER NOT NULL,
    rows_duplicate  INTEGER NOT NULL,
    rows_invalid    INTEGER NOT NULL,
    duration_s      REAL    NOT NULL,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS benchmark_runs (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    run_group         TEXT    NOT NULL,
    filter_type       TEXT    NOT NULL CHECK (filter_type IN ('standard', 'counting')),
    n_items           INTEGER NOT NULL,
    n_queries         INTEGER NOT NULL,
    fp_target         REAL    NOT NULL,
    m_bits            INTEGER NOT NULL,
    k_hashes          INTEGER NOT NULL,
    bloom_mem_bytes   INTEGER NOT NULL,
    set_mem_bytes     INTEGER NOT NULL,
    memory_ratio      REAL    NOT NULL,
    bloom_insert_s    REAL    NOT NULL,
    set_insert_s      REAL    NOT NULL,
    bloom_query_s     REAL    NOT NULL,
    set_query_s       REAL    NOT NULL,
    false_negatives   INTEGER NOT NULL,
    false_positives   INTEGER NOT NULL,
    seed              INTEGER NOT NULL,
    created_at        TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS fp_experiments (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    kind         TEXT    NOT NULL CHECK (kind IN ('vary_k', 'vary_ratio', 'overfill')),
    n_items      INTEGER NOT NULL,
    trials       INTEGER NOT NULL,
    seed         INTEGER NOT NULL,
    created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS fp_experiment_points (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id    INTEGER NOT NULL REFERENCES fp_experiments(id) ON DELETE CASCADE,
    param_label      TEXT    NOT NULL,
    m_bits           INTEGER NOT NULL,
    k_hashes         INTEGER NOT NULL,
    n_inserted       INTEGER NOT NULL,
    theoretical_fp   REAL    NOT NULL,
    empirical_fp     REAL    NOT NULL,
    false_positives  INTEGER NOT NULL,
    trials           INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_points_exp ON fp_experiment_points (experiment_id);
