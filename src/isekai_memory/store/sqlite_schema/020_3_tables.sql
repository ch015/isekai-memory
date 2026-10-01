-- SQLite baseline corresponding to PostgreSQL revision 020.
-- UUID/JSON/time type names preserve Python codecs; TEXT preserves affinity.

CREATE TABLE memory_presence_policies (
    project_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    policy JSONB TEXT NOT NULL,
    updated_by TEXT NOT NULL,
    updated_at TIMESTAMPTZ TEXT NOT NULL DEFAULT (CLOCK_TIMESTAMP()),
    CONSTRAINT memory_presence_policies_pkey PRIMARY KEY (project_id),
    CONSTRAINT memory_presence_policies_policy_check CHECK((JSONB_TYPEOF(policy) = CAST('object' AS TEXT))),
    CONSTRAINT memory_presence_policies_version_check CHECK((version > 0))
);

CREATE TABLE memory_presence_sessions (
    id UUID TEXT COLLATE NOCASE NOT NULL DEFAULT (GEN_RANDOM_UUID()),
    project_id TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    client_instance_id UUID TEXT COLLATE NOCASE NOT NULL,
    session_token_digest TEXT NOT NULL,
    register_digest TEXT NOT NULL,
    host_kind TEXT NOT NULL,
    session_kind TEXT NOT NULL,
    parent_session_id UUID TEXT COLLATE NOCASE,
    classification TEXT NOT NULL,
    sequence INTEGER NOT NULL DEFAULT (0),
    state_sequence INTEGER NOT NULL DEFAULT (0),
    report_digest TEXT,
    reported_policy_version INTEGER NOT NULL DEFAULT (0),
    reported_state TEXT NOT NULL DEFAULT (CAST('unknown' AS TEXT)),
    observation_scope TEXT NOT NULL DEFAULT (CAST('partial' AS TEXT)),
    state_observation_available BOOLEAN INTEGER NOT NULL DEFAULT (FALSE),
    active_work_count INTEGER NOT NULL DEFAULT (0),
    work_unit_id UUID TEXT COLLATE NOCASE,
    checkpoint_id UUID TEXT COLLATE NOCASE,
    created_at TIMESTAMPTZ TEXT NOT NULL DEFAULT (CLOCK_TIMESTAMP()),
    last_seen_at TIMESTAMPTZ TEXT NOT NULL DEFAULT (CLOCK_TIMESTAMP()),
    state_since_at TIMESTAMPTZ TEXT NOT NULL DEFAULT (CLOCK_TIMESTAMP()),
    idle_since_at TIMESTAMPTZ TEXT,
    ended_at TIMESTAMPTZ TEXT,
    retired_at TIMESTAMPTZ TEXT,
    CONSTRAINT memory_presence_sessions_active_work_count_check CHECK(((active_work_count >= 0) AND (active_work_count <= 128))),
    CONSTRAINT memory_presence_sessions_checkpoint_id_project_id_fkey FOREIGN KEY (checkpoint_id, project_id) REFERENCES memory_checkpoints(id, project_id) ON DELETE RESTRICT,
    CONSTRAINT memory_presence_sessions_classification_check CHECK((MEMORY_ARRAY_CONTAINS(JSON_ARRAY(CAST('public' AS TEXT), CAST('internal' AS TEXT), CAST('confidential' AS TEXT), CAST('restricted' AS TEXT)), classification))),
    CONSTRAINT memory_presence_sessions_host_kind_check CHECK((MEMORY_ARRAY_CONTAINS(JSON_ARRAY(CAST('codex' AS TEXT), CAST('claude' AS TEXT), CAST('kiro' AS TEXT), CAST('unknown' AS TEXT)), host_kind))),
    CONSTRAINT memory_presence_sessions_id_project_id_key UNIQUE (id, project_id),
    CONSTRAINT memory_presence_sessions_observation_scope_check CHECK((MEMORY_ARRAY_CONTAINS(JSON_ARRAY(CAST('worker' AS TEXT), CAST('controller' AS TEXT), CAST('partial' AS TEXT)), observation_scope))),
    CONSTRAINT memory_presence_sessions_parent_session_id_project_id_fkey FOREIGN KEY (parent_session_id, project_id) REFERENCES memory_presence_sessions(id, project_id) ON DELETE RESTRICT,
    CONSTRAINT memory_presence_sessions_pkey PRIMARY KEY (id),
    CONSTRAINT memory_presence_sessions_project_id_actor_id_client_instanc_key UNIQUE (project_id, actor_id, client_instance_id),
    CONSTRAINT memory_presence_sessions_reported_policy_version_check CHECK((reported_policy_version >= 0)),
    CONSTRAINT memory_presence_sessions_reported_state_check CHECK((MEMORY_ARRAY_CONTAINS(JSON_ARRAY(CAST('running' AS TEXT), CAST('waiting_approval' AS TEXT), CAST('blocked' AS TEXT), CAST('idle' AS TEXT), CAST('unknown' AS TEXT)), reported_state))),
    CONSTRAINT memory_presence_sessions_sequence_check CHECK((sequence >= 0)),
    CONSTRAINT memory_presence_sessions_session_kind_check CHECK((MEMORY_ARRAY_CONTAINS(JSON_ARRAY(CAST('worker' AS TEXT), CAST('controller' AS TEXT)), session_kind))),
    CONSTRAINT memory_presence_sessions_state_sequence_check CHECK((state_sequence >= 0)),
    CONSTRAINT memory_presence_sessions_work_unit_id_project_id_fkey FOREIGN KEY (work_unit_id, project_id) REFERENCES memory_continuity_units(id, project_id) ON DELETE RESTRICT
);
CREATE INDEX idx_presence_actor ON memory_presence_sessions(project_id, actor_id, created_at DESC, id DESC);
CREATE INDEX idx_presence_project ON memory_presence_sessions(project_id, last_seen_at DESC, id DESC) WHERE (retired_at IS NULL);

CREATE TABLE memory_project_members (
    project_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    role TEXT NOT NULL,
    assigned_by TEXT NOT NULL,
    CONSTRAINT memory_project_members_pkey PRIMARY KEY (project_id, user_id),
    CONSTRAINT memory_project_members_project_id_fkey FOREIGN KEY (project_id) REFERENCES memory_projects(project_id),
    CONSTRAINT memory_project_members_role_check CHECK((MEMORY_ARRAY_CONTAINS(JSON_ARRAY(CAST('read' AS TEXT), CAST('write' AS TEXT)), role)))
);
CREATE INDEX idx_memory_project_members_user ON memory_project_members(user_id, project_id);

CREATE TABLE memory_project_records (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    id UUID TEXT COLLATE NOCASE NOT NULL,
    project_id TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    unit_id TEXT,
    refs JSONB TEXT NOT NULL DEFAULT ('[]'),
    occurred_at TIMESTAMPTZ TEXT NOT NULL,
    created_at TIMESTAMPTZ TEXT NOT NULL DEFAULT (CLOCK_TIMESTAMP()),
    payload_digest TEXT NOT NULL,
    removed_at TIMESTAMPTZ TEXT,
    CONSTRAINT memory_project_records_id_key UNIQUE (id),
    CONSTRAINT memory_project_records_kind_check CHECK((MEMORY_ARRAY_CONTAINS(JSON_ARRAY(CAST('activity' AS TEXT), CAST('material' AS TEXT), CAST('result' AS TEXT)), kind))),
    CONSTRAINT memory_project_records_pkey UNIQUE (id),
    CONSTRAINT memory_project_records_project_id_actor_id_id_key UNIQUE (project_id, actor_id, id),
    CONSTRAINT memory_project_records_project_id_fkey FOREIGN KEY (project_id) REFERENCES memory_projects(project_id)
);
CREATE INDEX memory_project_records_page ON memory_project_records(project_id, sequence DESC) WHERE (removed_at IS NULL);

CREATE TABLE memory_projects (
    project_id TEXT NOT NULL,
    organization_id TEXT NOT NULL,
    name TEXT NOT NULL,
    git_url TEXT,
    git_ref TEXT,
    owner_id TEXT NOT NULL,
    setup JSONB TEXT NOT NULL,
    revision INTEGER NOT NULL,
    created_at TIMESTAMPTZ TEXT NOT NULL DEFAULT (TRANSACTION_TIMESTAMP()),
    updated_at TIMESTAMPTZ TEXT NOT NULL DEFAULT (TRANSACTION_TIMESTAMP()),
    source_kind TEXT NOT NULL DEFAULT (CAST('unknown' AS TEXT)),
    CONSTRAINT memory_projects_git_pair CHECK(((git_url IS NULL) = (git_ref IS NULL))),
    CONSTRAINT memory_projects_pkey PRIMARY KEY (project_id),
    CONSTRAINT memory_projects_revision_check CHECK((revision > 0)),
    CONSTRAINT memory_projects_source_git CHECK(((git_url IS NULL) OR (source_kind = CAST('git' AS TEXT)))),
    CONSTRAINT memory_projects_source_kind_check CHECK((MEMORY_ARRAY_CONTAINS(JSON_ARRAY(CAST('git' AS TEXT), CAST('directory' AS TEXT), CAST('unknown' AS TEXT)), source_kind)))
);
CREATE INDEX idx_memory_projects_owner ON memory_projects(owner_id, project_id);

CREATE TABLE memory_skill_events (
    revision_id UUID TEXT COLLATE NOCASE NOT NULL,
    version INTEGER NOT NULL,
    actor_id TEXT NOT NULL,
    action TEXT NOT NULL,
    previous_status TEXT NOT NULL,
    applied_status TEXT NOT NULL,
    cause_memory_id UUID TEXT COLLATE NOCASE,
    created_at TIMESTAMPTZ TEXT NOT NULL DEFAULT (CLOCK_TIMESTAMP()),
    CONSTRAINT memory_skill_events_pkey PRIMARY KEY (revision_id, version),
    CONSTRAINT memory_skill_events_revision_id_fkey FOREIGN KEY (revision_id) REFERENCES memory_skill_revisions(id) ON DELETE RESTRICT
);

CREATE TABLE memory_skill_imports (
    id UUID TEXT COLLATE NOCASE NOT NULL DEFAULT (GEN_RANDOM_UUID()),
    project_id TEXT NOT NULL,
    origin_key TEXT NOT NULL,
    archive_digest TEXT NOT NULL,
    artifact_digest TEXT NOT NULL,
    manifest_digest TEXT NOT NULL,
    classification TEXT NOT NULL,
    payload JSONB TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT (CAST('quarantined' AS TEXT)),
    version INTEGER NOT NULL DEFAULT (1),
    created_by TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    submission_digest TEXT NOT NULL,
    forgotten_by TEXT,
    created_at TIMESTAMPTZ TEXT NOT NULL DEFAULT (CLOCK_TIMESTAMP()),
    CONSTRAINT memory_skill_imports_check CHECK((((status = CAST('quarantined' AS TEXT)) AND (version = 1) AND (payload <> '{}') AND (forgotten_by IS NULL)) OR ((status = CAST('forgotten' AS TEXT)) AND (version = 2) AND (payload = '{}') AND (NOT forgotten_by IS NULL)))),
    CONSTRAINT memory_skill_imports_classification_check CHECK((MEMORY_ARRAY_CONTAINS(JSON_ARRAY(CAST('public' AS TEXT), CAST('internal' AS TEXT), CAST('confidential' AS TEXT), CAST('restricted' AS TEXT)), classification))),
    CONSTRAINT memory_skill_imports_pkey PRIMARY KEY (id),
    CONSTRAINT memory_skill_imports_project_id_created_by_idempotency_key_key UNIQUE (project_id, created_by, idempotency_key),
    CONSTRAINT memory_skill_imports_project_id_origin_key_key UNIQUE (project_id, origin_key),
    CONSTRAINT memory_skill_imports_status_check CHECK((MEMORY_ARRAY_CONTAINS(JSON_ARRAY(CAST('quarantined' AS TEXT), CAST('forgotten' AS TEXT)), status))),
    CONSTRAINT memory_skill_imports_version_check CHECK((MEMORY_ARRAY_CONTAINS(JSON_ARRAY(1, 2), version)))
);
CREATE INDEX idx_imports_project ON memory_skill_imports(project_id, status, created_at DESC, id DESC);

CREATE TABLE memory_skill_revisions (
    id UUID TEXT COLLATE NOCASE NOT NULL DEFAULT (GEN_RANDOM_UUID()),
    skill_id UUID TEXT COLLATE NOCASE NOT NULL,
    project_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    base_active_revision INTEGER,
    version INTEGER NOT NULL DEFAULT (1),
    status TEXT NOT NULL DEFAULT (CAST('pending' AS TEXT)),
    origin TEXT NOT NULL,
    body JSONB TEXT NOT NULL,
    classification TEXT NOT NULL,
    source_lock_digest TEXT NOT NULL,
    source_watermark TEXT NOT NULL,
    content_digest TEXT NOT NULL,
    created_by TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    submission_digest TEXT NOT NULL,
    approved_at TIMESTAMPTZ TEXT,
    created_at TIMESTAMPTZ TEXT NOT NULL DEFAULT (CLOCK_TIMESTAMP()),
    updated_at TIMESTAMPTZ TEXT NOT NULL DEFAULT (CLOCK_TIMESTAMP()),
    CONSTRAINT memory_skill_revisions_check CHECK(((status = CAST('forgotten' AS TEXT)) = (body = '{}'))),
    CONSTRAINT memory_skill_revisions_check1 CHECK(((status <> CAST('active' AS TEXT)) OR ((origin = CAST('manual' AS TEXT)) AND (NOT approved_at IS NULL)))),
    CONSTRAINT memory_skill_revisions_classification_check CHECK((MEMORY_ARRAY_CONTAINS(JSON_ARRAY(CAST('public' AS TEXT), CAST('internal' AS TEXT), CAST('confidential' AS TEXT), CAST('restricted' AS TEXT)), classification))),
    CONSTRAINT memory_skill_revisions_id_project_id_key UNIQUE (id, project_id),
    CONSTRAINT memory_skill_revisions_origin_check CHECK((MEMORY_ARRAY_CONTAINS(JSON_ARRAY(CAST('manual' AS TEXT), CAST('generated' AS TEXT)), origin))),
    CONSTRAINT memory_skill_revisions_pkey PRIMARY KEY (id),
    CONSTRAINT memory_skill_revisions_project_id_created_by_idempotency_ke_key UNIQUE (project_id, created_by, idempotency_key),
    CONSTRAINT memory_skill_revisions_revision_check CHECK((revision > 0)),
    CONSTRAINT memory_skill_revisions_skill_id_project_id_fkey FOREIGN KEY (skill_id, project_id) REFERENCES memory_skills(id, project_id) ON DELETE RESTRICT,
    CONSTRAINT memory_skill_revisions_skill_id_revision_key UNIQUE (skill_id, revision),
    CONSTRAINT memory_skill_revisions_status_check CHECK((MEMORY_ARRAY_CONTAINS(JSON_ARRAY(CAST('pending' AS TEXT), CAST('active' AS TEXT), CAST('rejected' AS TEXT), CAST('archived' AS TEXT), CAST('superseded' AS TEXT), CAST('stale' AS TEXT), CAST('forgotten' AS TEXT)), status))),
    CONSTRAINT memory_skill_revisions_version_check CHECK((version > 0))
);
CREATE UNIQUE INDEX idx_skill_active ON memory_skill_revisions(skill_id) WHERE (status = CAST('active' AS TEXT));
CREATE INDEX idx_skill_review ON memory_skill_revisions(project_id, status, created_at DESC, id DESC);

CREATE TABLE memory_skill_sources (
    revision_id UUID TEXT COLLATE NOCASE NOT NULL,
    project_id TEXT NOT NULL,
    memory_id UUID TEXT COLLATE NOCASE NOT NULL,
    memory_version INTEGER NOT NULL,
    binding JSONB TEXT NOT NULL,
    CONSTRAINT memory_skill_sources_memory_id_project_id_fkey FOREIGN KEY (memory_id, project_id) REFERENCES memory_experiences(id, project_id) ON DELETE RESTRICT,
    CONSTRAINT memory_skill_sources_pkey PRIMARY KEY (revision_id, memory_id),
    CONSTRAINT memory_skill_sources_revision_id_project_id_fkey FOREIGN KEY (revision_id, project_id) REFERENCES memory_skill_revisions(id, project_id) ON DELETE RESTRICT
);
CREATE INDEX idx_skill_source_memory ON memory_skill_sources(memory_id);

CREATE TABLE memory_skills (
    id UUID TEXT COLLATE NOCASE NOT NULL DEFAULT (GEN_RANDOM_UUID()),
    project_id TEXT NOT NULL,
    name TEXT NOT NULL,
    latest_revision INTEGER NOT NULL DEFAULT (0),
    active_revision INTEGER,
    classification TEXT NOT NULL,
    created_at TIMESTAMPTZ TEXT NOT NULL DEFAULT (CLOCK_TIMESTAMP()),
    CONSTRAINT memory_skills_id_project_id_key UNIQUE (id, project_id),
    CONSTRAINT memory_skills_pkey PRIMARY KEY (id),
    CONSTRAINT memory_skills_project_id_name_key UNIQUE (project_id, name)
);

CREATE TABLE memory_summary_snapshots (
    job_id UUID TEXT COLLATE NOCASE NOT NULL,
    project_id TEXT NOT NULL,
    source_watermark TEXT NOT NULL,
    scope JSONB TEXT NOT NULL,
    source_count INTEGER NOT NULL,
    dependencies JSONB TEXT NOT NULL,
    created_at TIMESTAMPTZ TEXT NOT NULL DEFAULT (CLOCK_TIMESTAMP()),
    CONSTRAINT memory_summary_snapshots_job_id_project_id_fkey FOREIGN KEY (job_id, project_id) REFERENCES memory_generation_jobs(id, project_id) ON DELETE RESTRICT,
    CONSTRAINT memory_summary_snapshots_pkey PRIMARY KEY (job_id)
);
CREATE INDEX idx_summary_scope ON memory_summary_snapshots(project_id, created_at DESC, job_id);

CREATE TABLE memory_usage_policies (
    project_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    policy JSONB TEXT NOT NULL,
    updated_by TEXT NOT NULL,
    updated_at TIMESTAMPTZ TEXT NOT NULL DEFAULT (CLOCK_TIMESTAMP()),
    CONSTRAINT memory_usage_policies_pkey PRIMARY KEY (project_id),
    CONSTRAINT memory_usage_policies_policy_check CHECK((JSONB_TYPEOF(policy) = CAST('object' AS TEXT))),
    CONSTRAINT memory_usage_policies_version_check CHECK((version > 0))
);

CREATE TABLE memory_usage_receipts (
    session_id UUID TEXT COLLATE NOCASE NOT NULL,
    project_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    request_digest TEXT NOT NULL,
    received_at TIMESTAMPTZ TEXT NOT NULL,
    bucket_at TIMESTAMPTZ TEXT NOT NULL,
    completion_state TEXT NOT NULL,
    CONSTRAINT memory_usage_receipts_pkey PRIMARY KEY (session_id, sequence),
    CONSTRAINT memory_usage_receipts_sequence_check CHECK((sequence > 0)),
    CONSTRAINT memory_usage_receipts_session_id_fkey FOREIGN KEY (session_id) REFERENCES memory_usage_sessions(id) ON DELETE RESTRICT,
    CONSTRAINT memory_usage_receipts_session_id_project_id_fkey FOREIGN KEY (session_id, project_id) REFERENCES memory_usage_sessions(id, project_id) ON DELETE RESTRICT
);
CREATE INDEX idx_usage_receipt_rate ON memory_usage_receipts(project_id, received_at);

CREATE TABLE memory_usage_sessions (
    id UUID TEXT COLLATE NOCASE NOT NULL DEFAULT (GEN_RANDOM_UUID()),
    project_id TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    execution_attempt_id UUID TEXT COLLATE NOCASE NOT NULL,
    meter_epoch UUID TEXT COLLATE NOCASE NOT NULL,
    session_token_digest TEXT NOT NULL,
    register_digest TEXT NOT NULL,
    host_kind TEXT NOT NULL,
    host_version TEXT NOT NULL,
    adapter_version TEXT NOT NULL,
    provider TEXT NOT NULL,
    model_id TEXT NOT NULL,
    classification TEXT NOT NULL,
    parent_session_id UUID TEXT COLLATE NOCASE,
    work_unit_id UUID TEXT COLLATE NOCASE,
    claim_generation INTEGER,
    created_at TIMESTAMPTZ TEXT NOT NULL DEFAULT (CLOCK_TIMESTAMP()),
    accepts_until TIMESTAMPTZ TEXT NOT NULL,
    sequence INTEGER NOT NULL DEFAULT (0),
    metrics JSONB TEXT,
    coverage TEXT NOT NULL DEFAULT (CAST('partial' AS TEXT)),
    completion_state TEXT NOT NULL DEFAULT (CAST('in_progress' AS TEXT)),
    first_received_at TIMESTAMPTZ TEXT,
    last_received_at TIMESTAMPTZ TEXT,
    bucket_at TIMESTAMPTZ TEXT,
    bucket_basis TEXT,
    source_occurred_at TIMESTAMPTZ TEXT,
    finalized_at TIMESTAMPTZ TEXT,
    retired_at TIMESTAMPTZ TEXT,
    CONSTRAINT memory_usage_sessions_bucket_basis_check CHECK((MEMORY_ARRAY_CONTAINS(JSON_ARRAY(CAST('source_reported' AS TEXT), CAST('server_first_received' AS TEXT), CAST('provisional' AS TEXT)), bucket_basis))),
    CONSTRAINT memory_usage_sessions_check CHECK(((work_unit_id IS NULL) = (claim_generation IS NULL))),
    CONSTRAINT memory_usage_sessions_check1 CHECK((accepts_until > created_at)),
    CONSTRAINT memory_usage_sessions_classification_check CHECK((MEMORY_ARRAY_CONTAINS(JSON_ARRAY(CAST('public' AS TEXT), CAST('internal' AS TEXT), CAST('confidential' AS TEXT), CAST('restricted' AS TEXT)), classification))),
    CONSTRAINT memory_usage_sessions_completion_state_check CHECK((MEMORY_ARRAY_CONTAINS(JSON_ARRAY(CAST('in_progress' AS TEXT), CAST('final' AS TEXT)), completion_state))),
    CONSTRAINT memory_usage_sessions_coverage_check CHECK((MEMORY_ARRAY_CONTAINS(JSON_ARRAY(CAST('partial' AS TEXT), CAST('complete' AS TEXT)), coverage))),
    CONSTRAINT memory_usage_sessions_host_kind_check CHECK((MEMORY_ARRAY_CONTAINS(JSON_ARRAY(CAST('codex' AS TEXT), CAST('claude' AS TEXT), CAST('kiro' AS TEXT), CAST('unknown' AS TEXT)), host_kind))),
    CONSTRAINT memory_usage_sessions_id_project_id_key UNIQUE (id, project_id),
    CONSTRAINT memory_usage_sessions_parent_session_id_project_id_fkey FOREIGN KEY (parent_session_id, project_id) REFERENCES memory_usage_sessions(id, project_id) ON DELETE RESTRICT,
    CONSTRAINT memory_usage_sessions_pkey PRIMARY KEY (id),
    CONSTRAINT memory_usage_sessions_project_id_actor_id_execution_attempt_key UNIQUE (project_id, actor_id, execution_attempt_id),
    CONSTRAINT memory_usage_sessions_sequence_check CHECK((sequence >= 0)),
    CONSTRAINT memory_usage_sessions_work_unit_id_project_id_fkey FOREIGN KEY (work_unit_id, project_id) REFERENCES memory_continuity_units(id, project_id) ON DELETE RESTRICT
);
CREATE INDEX idx_usage_actor ON memory_usage_sessions(project_id, actor_id, created_at DESC, id DESC);
CREATE INDEX idx_usage_bucket ON memory_usage_sessions(project_id, bucket_at, actor_id) WHERE (retired_at IS NULL);
