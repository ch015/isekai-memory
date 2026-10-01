-- SQLite baseline corresponding to PostgreSQL revision 020.
-- UUID/JSON/time type names preserve Python codecs; TEXT preserves affinity.

CREATE TABLE memory_continuity_policies (
    project_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    policy JSONB TEXT NOT NULL,
    updated_by TEXT NOT NULL,
    updated_at TIMESTAMPTZ TEXT NOT NULL DEFAULT (CLOCK_TIMESTAMP()),
    CONSTRAINT memory_continuity_policies_pkey PRIMARY KEY (project_id),
    CONSTRAINT memory_continuity_policies_policy_check CHECK((JSONB_TYPEOF(policy) = CAST('object' AS TEXT))),
    CONSTRAINT memory_continuity_policies_version_check CHECK((version > 0))
);

CREATE TABLE memory_continuity_receipts (
    project_id TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    operation TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_digest TEXT NOT NULL,
    result JSONB TEXT NOT NULL,
    created_at TIMESTAMPTZ TEXT NOT NULL DEFAULT (CLOCK_TIMESTAMP()),
    CONSTRAINT memory_continuity_receipts_pkey PRIMARY KEY (project_id, actor_id, operation, idempotency_key)
);

CREATE TABLE memory_continuity_units (
    id UUID TEXT COLLATE NOCASE NOT NULL DEFAULT (GEN_RANDOM_UUID()),
    project_id TEXT NOT NULL,
    bundle_id UUID TEXT COLLATE NOCASE NOT NULL,
    unit_key TEXT NOT NULL,
    summary TEXT NOT NULL,
    assignee_user_ids TEXT_ARRAY TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT (CAST('available' AS TEXT)),
    claimed_by TEXT,
    claim_token_digest TEXT,
    claim_generation INTEGER NOT NULL DEFAULT (0),
    lease_expires_at TIMESTAMPTZ TEXT,
    updated_at TIMESTAMPTZ TEXT NOT NULL DEFAULT (CLOCK_TIMESTAMP()),
    CONSTRAINT memory_continuity_units_assignee_user_ids_check CHECK(((CARDINALITY(assignee_user_ids) >= 1) AND (CARDINALITY(assignee_user_ids) <= 32))),
    CONSTRAINT memory_continuity_units_bundle_id_project_id_fkey FOREIGN KEY (bundle_id, project_id) REFERENCES memory_continuity_bundles(id, project_id) ON DELETE RESTRICT,
    CONSTRAINT memory_continuity_units_bundle_id_unit_key_key UNIQUE (bundle_id, unit_key),
    CONSTRAINT memory_continuity_units_check CHECK(((state <> CAST('claimed' AS TEXT)) OR ((NOT claimed_by IS NULL) AND (NOT claim_token_digest IS NULL) AND (NOT lease_expires_at IS NULL)))),
    CONSTRAINT memory_continuity_units_claim_generation_check CHECK((claim_generation >= 0)),
    CONSTRAINT memory_continuity_units_id_project_id_key UNIQUE (id, project_id),
    CONSTRAINT memory_continuity_units_pkey PRIMARY KEY (id),
    CONSTRAINT memory_continuity_units_state_check CHECK((MEMORY_ARRAY_CONTAINS(JSON_ARRAY(CAST('available' AS TEXT), CAST('claimed' AS TEXT), CAST('completed' AS TEXT), CAST('cancelled' AS TEXT)), state)))
);

CREATE TABLE memory_event_cursor_key (
    singleton INTEGER NOT NULL,
    secret BLOB NOT NULL,
    CONSTRAINT memory_event_cursor_key_pkey PRIMARY KEY (singleton),
    CONSTRAINT memory_event_cursor_key_secret_check CHECK((OCTET_LENGTH(secret) = 32)),
    CONSTRAINT memory_event_cursor_key_singleton_check CHECK((singleton = 1))
);

CREATE TABLE memory_event_heads (
    project_id TEXT NOT NULL,
    position INTEGER NOT NULL,
    pruned_through INTEGER NOT NULL DEFAULT (0),
    CONSTRAINT memory_event_heads_check CHECK(((pruned_through >= 0) AND (pruned_through <= "position"))),
    CONSTRAINT memory_event_heads_pkey PRIMARY KEY (project_id),
    CONSTRAINT memory_event_heads_position_check CHECK(("position" >= 0))
);

CREATE TABLE memory_experience_events (
    memory_id UUID TEXT COLLATE NOCASE NOT NULL,
    version INTEGER NOT NULL,
    actor_id TEXT NOT NULL,
    action TEXT NOT NULL,
    previous_status TEXT NOT NULL,
    applied_status TEXT NOT NULL,
    created_at TIMESTAMPTZ TEXT NOT NULL DEFAULT (TRANSACTION_TIMESTAMP()),
    related_memory_id UUID TEXT COLLATE NOCASE,
    CONSTRAINT ck_experience_event_transition CHECK((((action = CAST('approve' AS TEXT)) AND (previous_status = CAST('pending' AS TEXT)) AND (applied_status = CAST('active' AS TEXT))) OR ((action = CAST('reject' AS TEXT)) AND (previous_status = CAST('pending' AS TEXT)) AND (applied_status = CAST('rejected' AS TEXT))) OR ((action = CAST('archive' AS TEXT)) AND (previous_status = CAST('active' AS TEXT)) AND (applied_status = CAST('archived' AS TEXT))) OR ((action = CAST('supersede' AS TEXT)) AND (previous_status = CAST('active' AS TEXT)) AND (applied_status = CAST('superseded' AS TEXT))) OR ((action = CAST('forget' AS TEXT)) AND (MEMORY_ARRAY_CONTAINS(JSON_ARRAY(CAST('pending' AS TEXT), CAST('active' AS TEXT), CAST('rejected' AS TEXT), CAST('archived' AS TEXT), CAST('superseded' AS TEXT)), previous_status)) AND (applied_status = CAST('forgotten' AS TEXT))))),
    CONSTRAINT ck_experience_event_version CHECK((version >= 2)),
    CONSTRAINT memory_experience_events_memory_id_fkey FOREIGN KEY (memory_id) REFERENCES memory_experiences(id) ON DELETE CASCADE,
    CONSTRAINT memory_experience_events_pkey PRIMARY KEY (memory_id, version)
);

CREATE TABLE memory_experience_suppressions (
    project_id TEXT NOT NULL,
    source_payload_digest TEXT NOT NULL,
    content_fingerprint TEXT NOT NULL,
    memory_id UUID TEXT COLLATE NOCASE NOT NULL,
    reason TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT (1),
    updated_by TEXT NOT NULL,
    updated_at TIMESTAMPTZ TEXT NOT NULL DEFAULT (TRANSACTION_TIMESTAMP()),
    released_at TIMESTAMPTZ TEXT,
    CONSTRAINT ck_experience_suppression_reason CHECK((MEMORY_ARRAY_CONTAINS(JSON_ARRAY(CAST('rejected' AS TEXT), CAST('superseded' AS TEXT), CAST('forgotten' AS TEXT)), reason))),
    CONSTRAINT ck_experience_suppression_version CHECK((version >= 1)),
    CONSTRAINT memory_experience_suppressions_memory_id_fkey FOREIGN KEY (memory_id) REFERENCES memory_experiences(id) ON DELETE RESTRICT,
    CONSTRAINT memory_experience_suppressions_pkey PRIMARY KEY (project_id, source_payload_digest, content_fingerprint)
);

CREATE TABLE memory_experiences (
    id UUID TEXT COLLATE NOCASE NOT NULL DEFAULT (GEN_RANDOM_UUID()),
    project_id TEXT NOT NULL,
    source_handoff_id UUID TEXT COLLATE NOCASE,
    source JSONB TEXT NOT NULL,
    source_lock_digest TEXT NOT NULL,
    classification TEXT NOT NULL,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    tags TEXT_ARRAY TEXT NOT NULL,
    search_text TEXT NOT NULL,
    search_document TEXT GENERATED ALWAYS AS (search_text) STORED,
    status TEXT NOT NULL DEFAULT (CAST('pending' AS TEXT)),
    version INTEGER NOT NULL DEFAULT (1),
    created_by TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    submission_digest TEXT NOT NULL,
    expires_at TIMESTAMPTZ TEXT,
    created_at TIMESTAMPTZ TEXT NOT NULL DEFAULT (TRANSACTION_TIMESTAMP()),
    updated_at TIMESTAMPTZ TEXT NOT NULL DEFAULT (TRANSACTION_TIMESTAMP()),
    source_payload_digest TEXT NOT NULL,
    content_fingerprint TEXT NOT NULL,
    valid_from TIMESTAMPTZ TEXT,
    supersedes_id UUID TEXT COLLATE NOCASE,
    supersedes_version INTEGER,
    revision_root_id UUID TEXT COLLATE NOCASE,
    revision_number INTEGER NOT NULL DEFAULT (1),
    is_correction BOOLEAN INTEGER NOT NULL DEFAULT (FALSE),
    CONSTRAINT ck_experience_classification CHECK((MEMORY_ARRAY_CONTAINS(JSON_ARRAY(CAST('public' AS TEXT), CAST('internal' AS TEXT), CAST('confidential' AS TEXT), CAST('restricted' AS TEXT)), classification))),
    CONSTRAINT ck_experience_content CHECK(((LENGTH(content) >= 1) AND (LENGTH(content) <= 4096))),
    CONSTRAINT ck_experience_forgotten CHECK((((status = CAST('forgotten' AS TEXT)) AND (source_handoff_id IS NULL) AND (source = '{}') AND (title = CAST('[forgotten]' AS TEXT)) AND (content = CAST('[forgotten]' AS TEXT)) AND (CARDINALITY(tags) = 0) AND (search_text = CAST('' AS TEXT))) OR ((status <> CAST('forgotten' AS TEXT)) AND (NOT source_handoff_id IS NULL)))),
    CONSTRAINT ck_experience_kind CHECK((MEMORY_ARRAY_CONTAINS(JSON_ARRAY(CAST('fact' AS TEXT), CAST('decision' AS TEXT), CAST('constraint' AS TEXT), CAST('lesson' AS TEXT), CAST('procedure' AS TEXT)), kind))),
    CONSTRAINT ck_experience_revision CHECK((((supersedes_id IS NULL) AND (supersedes_version IS NULL) AND (revision_root_id IS NULL) AND (revision_number = 1) AND (NOT is_correction)) OR ((NOT supersedes_id IS NULL) AND (supersedes_id <> id) AND (NOT supersedes_version IS NULL) AND (supersedes_version >= 1) AND (NOT revision_root_id IS NULL) AND (revision_root_id <> id) AND (revision_number > 1) AND is_correction))),
    CONSTRAINT ck_experience_status CHECK((MEMORY_ARRAY_CONTAINS(JSON_ARRAY(CAST('pending' AS TEXT), CAST('active' AS TEXT), CAST('rejected' AS TEXT), CAST('archived' AS TEXT), CAST('superseded' AS TEXT), CAST('forgotten' AS TEXT)), status))),
    CONSTRAINT ck_experience_tags CHECK((CARDINALITY(tags) <= 16)),
    CONSTRAINT ck_experience_title CHECK(((LENGTH(title) >= 1) AND (LENGTH(title) <= 200))),
    CONSTRAINT ck_experience_validity CHECK(((valid_from IS NULL) OR (expires_at IS NULL) OR (valid_from < expires_at))),
    CONSTRAINT ck_experience_version CHECK((version >= 1)),
    CONSTRAINT fk_experience_revision_root_id FOREIGN KEY (revision_root_id, project_id) REFERENCES memory_experiences(id, project_id) ON DELETE RESTRICT,
    CONSTRAINT fk_experience_source_project FOREIGN KEY (source_handoff_id, project_id) REFERENCES handoffs(id, project_id) ON DELETE RESTRICT,
    CONSTRAINT fk_experience_supersedes_id FOREIGN KEY (supersedes_id, project_id) REFERENCES memory_experiences(id, project_id) ON DELETE RESTRICT,
    CONSTRAINT memory_experiences_pkey PRIMARY KEY (id),
    CONSTRAINT uq_experience_id_project UNIQUE (id, project_id),
    CONSTRAINT uq_experience_submission UNIQUE (project_id, created_by, idempotency_key)
);
CREATE INDEX idx_experience_family ON memory_experiences(project_id, COALESCE(revision_root_id, id), created_at, id);
CREATE INDEX idx_experiences_project_status ON memory_experiences(project_id, status, created_at, id);
CREATE INDEX idx_experiences_source ON memory_experiences(source_handoff_id, project_id);
CREATE UNIQUE INDEX uq_experience_active_family ON memory_experiences(COALESCE(revision_root_id, id)) WHERE (status = CAST('active' AS TEXT));

CREATE TABLE memory_generation_attempts (
    job_id UUID TEXT COLLATE NOCASE NOT NULL,
    attempt INTEGER NOT NULL,
    started_at TIMESTAMPTZ TEXT NOT NULL DEFAULT (CLOCK_TIMESTAMP()),
    finished_at TIMESTAMPTZ TEXT,
    outcome_code TEXT,
    input_chars INTEGER NOT NULL DEFAULT (0),
    output_chars INTEGER NOT NULL DEFAULT (0),
    cost_microusd INTEGER NOT NULL DEFAULT (0),
    CONSTRAINT memory_generation_attempts_cost_microusd_check CHECK((cost_microusd = 0)),
    CONSTRAINT memory_generation_attempts_job_id_fkey FOREIGN KEY (job_id) REFERENCES memory_generation_jobs(id) ON DELETE RESTRICT,
    CONSTRAINT memory_generation_attempts_pkey PRIMARY KEY (job_id, attempt)
);

CREATE TABLE memory_generation_jobs (
    id UUID TEXT COLLATE NOCASE NOT NULL DEFAULT (GEN_RANDOM_UUID()),
    project_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    source_key TEXT NOT NULL,
    source_watermark TEXT NOT NULL,
    recipe TEXT NOT NULL,
    provider TEXT NOT NULL,
    model_version TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    parameters JSONB TEXT NOT NULL,
    enqueued_by TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT (CAST('queued' AS TEXT)),
    version INTEGER NOT NULL DEFAULT (1),
    attempts INTEGER NOT NULL DEFAULT (0),
    max_attempts INTEGER NOT NULL DEFAULT (3),
    lease_token UUID TEXT COLLATE NOCASE,
    lease_until TIMESTAMPTZ TEXT,
    available_at TIMESTAMPTZ TEXT NOT NULL DEFAULT (TRANSACTION_TIMESTAMP()),
    error_code TEXT,
    outcome JSONB TEXT,
    redrive_version INTEGER,
    redrive_actor TEXT,
    created_at TIMESTAMPTZ TEXT NOT NULL DEFAULT (TRANSACTION_TIMESTAMP()),
    updated_at TIMESTAMPTZ TEXT NOT NULL DEFAULT (TRANSACTION_TIMESTAMP()),
    CONSTRAINT memory_generation_jobs_attempts_check CHECK((attempts >= 0)),
    CONSTRAINT memory_generation_jobs_check CHECK(((status = CAST('running' AS TEXT)) = ((NOT lease_token IS NULL) AND (NOT lease_until IS NULL)))),
    CONSTRAINT memory_generation_jobs_id_project_id_key UNIQUE (id, project_id),
    CONSTRAINT memory_generation_jobs_kind_check CHECK((MEMORY_ARRAY_CONTAINS(JSON_ARRAY(CAST('extract' AS TEXT), CAST('summary' AS TEXT), CAST('skill' AS TEXT)), kind))),
    CONSTRAINT memory_generation_jobs_max_attempts_check CHECK(((max_attempts >= 1) AND (max_attempts <= 30))),
    CONSTRAINT memory_generation_jobs_pkey PRIMARY KEY (id),
    CONSTRAINT memory_generation_jobs_project_id_kind_source_key_source_wa_key UNIQUE (project_id, kind, source_key, source_watermark, recipe),
    CONSTRAINT memory_generation_jobs_status_check CHECK((MEMORY_ARRAY_CONTAINS(JSON_ARRAY(CAST('queued' AS TEXT), CAST('running' AS TEXT), CAST('succeeded' AS TEXT), CAST('dead' AS TEXT)), status))),
    CONSTRAINT memory_generation_jobs_version_check CHECK((version > 0))
);
CREATE INDEX idx_generation_ready ON memory_generation_jobs(project_id, status, available_at, created_at, id);

CREATE TABLE memory_github_identities (
    github_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    organization_id TEXT NOT NULL,
    disabled_at TIMESTAMPTZ TEXT,
    created_at TIMESTAMPTZ TEXT NOT NULL DEFAULT (TRANSACTION_TIMESTAMP()),
    CONSTRAINT memory_github_identities_github_id_check CHECK((REGEXP(CAST('^[1-9][0-9]{0,19}$' AS TEXT), github_id))),
    CONSTRAINT memory_github_identities_pkey PRIMARY KEY (github_id),
    CONSTRAINT memory_github_identities_user_id_key UNIQUE (user_id)
);

CREATE TABLE memory_identities (
    tenant_id TEXT NOT NULL,
    object_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    organization_id TEXT NOT NULL,
    disabled_at TIMESTAMPTZ TEXT,
    created_at TIMESTAMPTZ TEXT NOT NULL DEFAULT (TRANSACTION_TIMESTAMP()),
    CONSTRAINT memory_identities_pkey PRIMARY KEY (tenant_id, object_id),
    CONSTRAINT memory_identities_user_id_key UNIQUE (user_id)
);

CREATE TABLE memory_knowledge_documents (
    id UUID TEXT COLLATE NOCASE NOT NULL DEFAULT (GEN_RANDOM_UUID()),
    project_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    source_key TEXT NOT NULL,
    source_revision TEXT NOT NULL,
    version INTEGER NOT NULL,
    classification TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    content_digest TEXT NOT NULL,
    status TEXT NOT NULL,
    valid_until TIMESTAMPTZ TEXT NOT NULL,
    created_at TIMESTAMPTZ TEXT NOT NULL DEFAULT (CLOCK_TIMESTAMP()),
    updated_at TIMESTAMPTZ TEXT NOT NULL DEFAULT (CLOCK_TIMESTAMP()),
    CONSTRAINT memory_knowledge_documents_check CHECK((((status = CAST('deleted' AS TEXT)) AND (title = CAST('' AS TEXT)) AND (content = CAST('' AS TEXT))) OR ((status = CAST('active' AS TEXT)) AND ((LENGTH(title) >= 1) AND (LENGTH(title) <= 200)) AND ((LENGTH(content) >= 1) AND (LENGTH(content) <= 8192))))),
    CONSTRAINT memory_knowledge_documents_classification_check CHECK((MEMORY_ARRAY_CONTAINS(JSON_ARRAY(CAST('public' AS TEXT), CAST('internal' AS TEXT), CAST('confidential' AS TEXT), CAST('restricted' AS TEXT)), classification))),
    CONSTRAINT memory_knowledge_documents_id_project_id_key UNIQUE (id, project_id),
    CONSTRAINT memory_knowledge_documents_pkey PRIMARY KEY (id),
    CONSTRAINT memory_knowledge_documents_project_id_provider_source_key_key UNIQUE (project_id, provider, source_key),
    CONSTRAINT memory_knowledge_documents_provider_check CHECK((provider = CAST('pushed_wiki_v1' AS TEXT))),
    CONSTRAINT memory_knowledge_documents_status_check CHECK((MEMORY_ARRAY_CONTAINS(JSON_ARRAY(CAST('active' AS TEXT), CAST('deleted' AS TEXT)), status))),
    CONSTRAINT memory_knowledge_documents_version_check CHECK((version > 0))
);
CREATE INDEX idx_knowledge_project ON memory_knowledge_documents(project_id, created_at DESC, id DESC);

CREATE TABLE memory_knowledge_events (
    document_id UUID TEXT COLLATE NOCASE NOT NULL,
    version INTEGER NOT NULL,
    actor_id TEXT NOT NULL,
    action TEXT NOT NULL,
    source_revision TEXT,
    submission_digest TEXT NOT NULL,
    created_at TIMESTAMPTZ TEXT NOT NULL DEFAULT (CLOCK_TIMESTAMP()),
    CONSTRAINT memory_knowledge_events_action_check CHECK((MEMORY_ARRAY_CONTAINS(JSON_ARRAY(CAST('sync' AS TEXT), CAST('delete' AS TEXT)), action))),
    CONSTRAINT memory_knowledge_events_document_id_fkey FOREIGN KEY (document_id) REFERENCES memory_knowledge_documents(id) ON DELETE RESTRICT,
    CONSTRAINT memory_knowledge_events_document_id_source_revision_key UNIQUE (document_id, source_revision),
    CONSTRAINT memory_knowledge_events_pkey PRIMARY KEY (document_id, version)
);
