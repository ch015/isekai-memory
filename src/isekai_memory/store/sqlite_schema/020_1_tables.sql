-- SQLite baseline corresponding to PostgreSQL revision 020.
-- UUID/JSON/time type names preserve Python codecs; TEXT preserves affinity.

CREATE TABLE access_tokens (
    id UUID TEXT COLLATE NOCASE NOT NULL DEFAULT (GEN_RANDOM_UUID()),
    token_hash TEXT NOT NULL,
    project_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    scopes TEXT_ARRAY TEXT NOT NULL DEFAULT ('["read","write"]'),
    expires_at TIMESTAMPTZ TEXT,
    created_at TIMESTAMPTZ TEXT NOT NULL DEFAULT (TRANSACTION_TIMESTAMP()),
    revoked_at TIMESTAMPTZ TEXT,
    CONSTRAINT access_tokens_pkey PRIMARY KEY (id),
    CONSTRAINT access_tokens_token_hash_key UNIQUE (token_hash)
);
CREATE INDEX idx_tokens_hash ON access_tokens(token_hash);

CREATE TABLE alembic_version (
    version_num TEXT NOT NULL,
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

CREATE TABLE artifact_policies (
    id UUID TEXT COLLATE NOCASE NOT NULL DEFAULT (GEN_RANDOM_UUID()),
    organization_id TEXT NOT NULL,
    project_pattern TEXT NOT NULL DEFAULT (CAST('*' AS TEXT)),
    kind TEXT NOT NULL,
    artifact_id TEXT NOT NULL,
    version_range TEXT NOT NULL,
    required BOOLEAN INTEGER NOT NULL DEFAULT (TRUE),
    priority INTEGER NOT NULL DEFAULT (0),
    created_at TIMESTAMPTZ TEXT NOT NULL DEFAULT (TRANSACTION_TIMESTAMP()),
    updated_at TIMESTAMPTZ TEXT NOT NULL DEFAULT (TRANSACTION_TIMESTAMP()),
    CONSTRAINT artifact_policies_pkey PRIMARY KEY (id),
    CONSTRAINT uq_policy_identity UNIQUE (organization_id, project_pattern, kind, artifact_id)
);
CREATE INDEX idx_policies_org ON artifact_policies(organization_id);

CREATE TABLE artifacts (
    id UUID TEXT COLLATE NOCASE NOT NULL DEFAULT (GEN_RANDOM_UUID()),
    artifact_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    version TEXT NOT NULL,
    manifest_digest TEXT NOT NULL,
    artifact_digest TEXT NOT NULL,
    archive_blob BLOB,
    archive_url TEXT,
    published_by TEXT NOT NULL,
    published_at TIMESTAMPTZ TEXT NOT NULL DEFAULT (TRANSACTION_TIMESTAMP()),
    metadata JSONB TEXT NOT NULL DEFAULT ('{}'),
    archive_digest TEXT NOT NULL,
    CONSTRAINT artifacts_pkey PRIMARY KEY (id),
    CONSTRAINT ck_artifacts_kind CHECK((MEMORY_ARRAY_CONTAINS(JSON_ARRAY(CAST('foundation' AS TEXT), CAST('preset' AS TEXT)), kind))),
    CONSTRAINT ck_artifacts_storage CHECK((((NOT archive_blob IS NULL) AND (archive_url IS NULL)) OR ((archive_blob IS NULL) AND (NOT archive_url IS NULL)))),
    CONSTRAINT uq_artifact_identity UNIQUE (artifact_id, kind, version)
);
CREATE INDEX idx_artifacts_kind_id ON artifacts(kind, artifact_id);

CREATE TABLE handoff_claim_receipts (
    id UUID TEXT COLLATE NOCASE NOT NULL DEFAULT (GEN_RANDOM_UUID()),
    handoff_id UUID TEXT COLLATE NOCASE NOT NULL,
    project_id TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    claim_token_digest TEXT NOT NULL,
    claim_generation INTEGER NOT NULL,
    operation TEXT NOT NULL,
    reason_code TEXT,
    created_at TIMESTAMPTZ TEXT NOT NULL DEFAULT (TRANSACTION_TIMESTAMP()),
    CONSTRAINT ck_handoff_receipt_operation CHECK((MEMORY_ARRAY_CONTAINS(JSON_ARRAY(CAST('acknowledged' AS TEXT), CAST('nacked' AS TEXT)), operation))),
    CONSTRAINT ck_handoff_receipt_reason CHECK(((reason_code IS NULL) OR (MEMORY_ARRAY_CONTAINS(JSON_ARRAY(CAST('retryable' AS TEXT), CAST('processing_failed' AS TEXT), CAST('shutdown' AS TEXT), CAST('cancelled' AS TEXT)), reason_code)))),
    CONSTRAINT handoff_claim_receipts_handoff_id_fkey FOREIGN KEY (handoff_id) REFERENCES handoffs(id) ON DELETE CASCADE,
    CONSTRAINT handoff_claim_receipts_pkey PRIMARY KEY (id),
    CONSTRAINT uq_handoff_claim_receipt UNIQUE (handoff_id, project_id, actor_id, claim_token_digest, operation)
);
CREATE INDEX idx_handoff_claim_receipts_guard ON handoff_claim_receipts(handoff_id, project_id, actor_id, claim_token_digest);

CREATE TABLE handoffs (
    id UUID TEXT COLLATE NOCASE NOT NULL DEFAULT (GEN_RANDOM_UUID()),
    project_id TEXT NOT NULL,
    unit_id TEXT NOT NULL,
    phase_attempt_id TEXT NOT NULL,
    phase_id TEXT NOT NULL,
    from_user TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT (CAST('pending' AS TEXT)),
    created_at TIMESTAMPTZ TEXT NOT NULL DEFAULT (TRANSACTION_TIMESTAMP()),
    claimed_by TEXT,
    claimed_at TIMESTAMPTZ TEXT,
    expires_at TIMESTAMPTZ TEXT,
    task_summary TEXT,
    result_status TEXT NOT NULL,
    passed_checks JSONB TEXT DEFAULT ('[]'),
    artifacts_produced JSONB TEXT DEFAULT ('[]'),
    handoff_note TEXT,
    task_envelope JSONB TEXT NOT NULL,
    result_envelope JSONB TEXT NOT NULL,
    context_digest TEXT NOT NULL,
    raw_output TEXT,
    lock_snapshot_digest TEXT NOT NULL,
    envelope_digest TEXT NOT NULL,
    payload_digest TEXT NOT NULL,
    classification TEXT NOT NULL DEFAULT (CAST('internal' AS TEXT)),
    claim_token_digest TEXT,
    claim_lease_expires_at TIMESTAMPTZ TEXT,
    claim_generation INTEGER NOT NULL DEFAULT (0),
    claim_disposition TEXT,
    claim_reason_code TEXT,
    handoff_version INTEGER NOT NULL DEFAULT (CAST('1' AS INTEGER)),
    recipient_user_id TEXT,
    continuation JSONB TEXT,
    continuation_digest TEXT,
    continuity_managed BOOLEAN INTEGER NOT NULL DEFAULT (FALSE),
    compatibility_digest TEXT,
    CONSTRAINT ck_handoffs_claim_disposition CHECK(((claim_disposition IS NULL) OR (MEMORY_ARRAY_CONTAINS(JSON_ARRAY(CAST('acknowledged' AS TEXT), CAST('nacked' AS TEXT)), claim_disposition)))),
    CONSTRAINT ck_handoffs_claim_reason CHECK(((claim_reason_code IS NULL) OR (MEMORY_ARRAY_CONTAINS(JSON_ARRAY(CAST('retryable' AS TEXT), CAST('processing_failed' AS TEXT), CAST('shutdown' AS TEXT), CAST('cancelled' AS TEXT)), claim_reason_code)))),
    CONSTRAINT ck_handoffs_classification CHECK((MEMORY_ARRAY_CONTAINS(JSON_ARRAY(CAST('public' AS TEXT), CAST('internal' AS TEXT), CAST('confidential' AS TEXT), CAST('restricted' AS TEXT)), classification))),
    CONSTRAINT ck_handoffs_continuation CHECK((((handoff_version = 1) AND (recipient_user_id IS NULL) AND (continuation IS NULL) AND (continuation_digest IS NULL)) OR ((handoff_version = 2) AND ((NOT recipient_user_id IS NULL) OR (NOT continuation IS NULL)) AND (((continuation IS NULL) AND (continuation_digest IS NULL)) OR ((NOT continuation IS NULL) AND (NOT continuation_digest IS NULL) AND (JSONB_TYPEOF(continuation) = CAST('object' AS TEXT)) AND (REGEXP(CAST('^sha256:[0-9a-f]{64}$' AS TEXT), continuation_digest))))))),
    CONSTRAINT ck_handoffs_recipient CHECK(((recipient_user_id IS NULL) OR ((LENGTH(recipient_user_id) >= 1) AND (LENGTH(recipient_user_id) <= 128)))),
    CONSTRAINT ck_handoffs_result_status CHECK((MEMORY_ARRAY_CONTAINS(JSON_ARRAY(CAST('succeeded' AS TEXT), CAST('failed' AS TEXT), CAST('cancelled' AS TEXT), CAST('lost' AS TEXT)), result_status))),
    CONSTRAINT ck_handoffs_status CHECK((MEMORY_ARRAY_CONTAINS(JSON_ARRAY(CAST('pending' AS TEXT), CAST('claimed' AS TEXT), CAST('acknowledged' AS TEXT), CAST('expired' AS TEXT)), status))),
    CONSTRAINT handoffs_compatibility_digest_check CHECK((REGEXP(CAST('^sha256:[0-9a-f]{64}$' AS TEXT), compatibility_digest))),
    CONSTRAINT handoffs_pkey PRIMARY KEY (id),
    CONSTRAINT uq_handoff_phase_attempt UNIQUE (project_id, phase_attempt_id),
    CONSTRAINT uq_handoffs_id_project UNIQUE (id, project_id)
);
CREATE INDEX idx_handoffs_claim_owner ON handoffs(project_id, claimed_by, status) WHERE (NOT claim_token_digest IS NULL);
CREATE INDEX idx_handoffs_project_status ON handoffs(project_id, status) WHERE (status = CAST('pending' AS TEXT));
CREATE INDEX idx_handoffs_recipient ON handoffs(project_id, recipient_user_id, status, created_at, id) WHERE (handoff_version = 2);
CREATE INDEX idx_handoffs_recoverable_claims ON handoffs(project_id, status, claim_lease_expires_at) WHERE (MEMORY_ARRAY_CONTAINS(JSON_ARRAY(CAST('pending' AS TEXT), CAST('claimed' AS TEXT)), status));
CREATE INDEX idx_handoffs_unit ON handoffs(project_id, unit_id, created_at DESC);

CREATE TABLE memory_asset_feedback (
    id UUID TEXT COLLATE NOCASE NOT NULL DEFAULT (GEN_RANDOM_UUID()),
    project_id TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    asset_kind TEXT NOT NULL,
    asset_id UUID TEXT COLLATE NOCASE NOT NULL,
    asset_version INTEGER NOT NULL,
    asset_digest TEXT NOT NULL,
    owner_project_id TEXT NOT NULL,
    grant_id UUID TEXT COLLATE NOCASE,
    usefulness TEXT NOT NULL,
    outcome TEXT NOT NULL,
    handoff_id UUID TEXT COLLATE NOCASE,
    evidence_digest TEXT,
    idempotency_key TEXT NOT NULL,
    submission_digest TEXT NOT NULL,
    created_at TIMESTAMPTZ TEXT NOT NULL DEFAULT (CLOCK_TIMESTAMP()),
    CONSTRAINT memory_asset_feedback_asset_kind_check CHECK((MEMORY_ARRAY_CONTAINS(JSON_ARRAY(CAST('experience' AS TEXT), CAST('skill' AS TEXT), CAST('knowledge' AS TEXT)), asset_kind))),
    CONSTRAINT memory_asset_feedback_asset_version_check CHECK((asset_version > 0)),
    CONSTRAINT memory_asset_feedback_check CHECK((((outcome = CAST('not_attempted' AS TEXT)) AND (handoff_id IS NULL) AND (evidence_digest IS NULL)) OR ((outcome <> CAST('not_attempted' AS TEXT)) AND (NOT handoff_id IS NULL) AND (NOT evidence_digest IS NULL)))),
    CONSTRAINT memory_asset_feedback_grant_id_fkey FOREIGN KEY (grant_id) REFERENCES memory_asset_grants(id),
    CONSTRAINT memory_asset_feedback_handoff_id_project_id_fkey FOREIGN KEY (handoff_id, project_id) REFERENCES handoffs(id, project_id) ON DELETE RESTRICT,
    CONSTRAINT memory_asset_feedback_outcome_check CHECK((MEMORY_ARRAY_CONTAINS(JSON_ARRAY(CAST('not_attempted' AS TEXT), CAST('succeeded' AS TEXT), CAST('failed' AS TEXT)), outcome))),
    CONSTRAINT memory_asset_feedback_pkey PRIMARY KEY (id),
    CONSTRAINT memory_asset_feedback_project_id_actor_id_asset_kind_asset__key UNIQUE (project_id, actor_id, asset_kind, asset_id, asset_version),
    CONSTRAINT memory_asset_feedback_project_id_actor_id_idempotency_key_key UNIQUE (project_id, actor_id, idempotency_key),
    CONSTRAINT memory_asset_feedback_usefulness_check CHECK((MEMORY_ARRAY_CONTAINS(JSON_ARRAY(CAST('helpful' AS TEXT), CAST('not_helpful' AS TEXT), CAST('uncertain' AS TEXT)), usefulness)))
);
CREATE INDEX idx_feedback_project ON memory_asset_feedback(project_id, created_at DESC, id DESC);

CREATE TABLE memory_asset_grants (
    id UUID TEXT COLLATE NOCASE NOT NULL DEFAULT (GEN_RANDOM_UUID()),
    project_id TEXT NOT NULL,
    consumer_project_id TEXT NOT NULL,
    asset_kind TEXT NOT NULL,
    asset_id UUID TEXT COLLATE NOCASE NOT NULL,
    asset_version INTEGER NOT NULL,
    asset_digest TEXT NOT NULL,
    classification TEXT NOT NULL,
    expires_at TIMESTAMPTZ TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT (1),
    revoked_at TIMESTAMPTZ TEXT,
    revoked_by TEXT,
    created_by TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    submission_digest TEXT NOT NULL,
    created_at TIMESTAMPTZ TEXT NOT NULL DEFAULT (CLOCK_TIMESTAMP()),
    CONSTRAINT memory_asset_grants_asset_kind_check CHECK((MEMORY_ARRAY_CONTAINS(JSON_ARRAY(CAST('experience' AS TEXT), CAST('skill' AS TEXT), CAST('knowledge' AS TEXT)), asset_kind))),
    CONSTRAINT memory_asset_grants_asset_version_check CHECK((asset_version > 0)),
    CONSTRAINT memory_asset_grants_check CHECK((project_id <> consumer_project_id)),
    CONSTRAINT memory_asset_grants_check1 CHECK((((version = 1) AND (revoked_at IS NULL) AND (revoked_by IS NULL)) OR ((version = 2) AND (NOT revoked_at IS NULL) AND (NOT revoked_by IS NULL)))),
    CONSTRAINT memory_asset_grants_pkey PRIMARY KEY (id),
    CONSTRAINT memory_asset_grants_project_id_created_by_idempotency_key_key UNIQUE (project_id, created_by, idempotency_key),
    CONSTRAINT memory_asset_grants_version_check CHECK((MEMORY_ARRAY_CONTAINS(JSON_ARRAY(1, 2), version)))
);
CREATE INDEX idx_asset_grants_owner ON memory_asset_grants(project_id, created_at DESC, id DESC);

CREATE TABLE memory_checkpoints (
    id UUID TEXT COLLATE NOCASE NOT NULL DEFAULT (GEN_RANDOM_UUID()),
    project_id TEXT NOT NULL,
    work_id TEXT NOT NULL,
    from_user TEXT NOT NULL,
    version INTEGER NOT NULL,
    classification TEXT NOT NULL,
    lock_snapshot_digest TEXT NOT NULL,
    continuation JSONB TEXT NOT NULL,
    continuation_digest TEXT NOT NULL,
    snapshot JSONB TEXT,
    snapshot_digest TEXT,
    payload_digest TEXT NOT NULL,
    policy_version INTEGER NOT NULL,
    expires_at TIMESTAMPTZ TEXT NOT NULL,
    forgotten_at TIMESTAMPTZ TEXT,
    created_at TIMESTAMPTZ TEXT NOT NULL DEFAULT (CLOCK_TIMESTAMP()),
    CONSTRAINT memory_checkpoints_check CHECK((((snapshot IS NULL) = (snapshot_digest IS NULL)) OR (NOT forgotten_at IS NULL))),
    CONSTRAINT memory_checkpoints_classification_check CHECK((MEMORY_ARRAY_CONTAINS(JSON_ARRAY(CAST('public' AS TEXT), CAST('internal' AS TEXT), CAST('confidential' AS TEXT), CAST('restricted' AS TEXT)), classification))),
    CONSTRAINT memory_checkpoints_id_project_id_key UNIQUE (id, project_id),
    CONSTRAINT memory_checkpoints_pkey PRIMARY KEY (id),
    CONSTRAINT memory_checkpoints_project_id_from_user_work_id_version_key UNIQUE (project_id, from_user, work_id, version),
    CONSTRAINT memory_checkpoints_version_check CHECK((version > 0))
);
CREATE INDEX idx_checkpoints_project ON memory_checkpoints(project_id, created_at DESC, id DESC);

CREATE TABLE memory_collaboration_events (
    project_id TEXT NOT NULL,
    position INTEGER NOT NULL,
    id UUID TEXT COLLATE NOCASE NOT NULL DEFAULT (GEN_RANDOM_UUID()),
    topic TEXT NOT NULL,
    resource_kind TEXT NOT NULL,
    resource_id UUID TEXT COLLATE NOCASE,
    classification TEXT NOT NULL,
    audience TEXT_ARRAY TEXT NOT NULL,
    broadcast BOOLEAN INTEGER NOT NULL DEFAULT (FALSE),
    revision INTEGER,
    created_at TIMESTAMPTZ TEXT NOT NULL DEFAULT (CLOCK_TIMESTAMP()),
    CONSTRAINT memory_collaboration_events_audience_check CHECK((CARDINALITY(audience) <= 128)),
    CONSTRAINT memory_collaboration_events_check CHECK(((resource_kind = CAST('signal' AS TEXT)) = (resource_id IS NULL))),
    CONSTRAINT memory_collaboration_events_classification_check CHECK((MEMORY_ARRAY_CONTAINS(JSON_ARRAY(CAST('public' AS TEXT), CAST('internal' AS TEXT), CAST('confidential' AS TEXT), CAST('restricted' AS TEXT)), classification))),
    CONSTRAINT memory_collaboration_events_id_key UNIQUE (id),
    CONSTRAINT memory_collaboration_events_pkey PRIMARY KEY (project_id, "position"),
    CONSTRAINT memory_collaboration_events_position_check CHECK(("position" > 0)),
    CONSTRAINT memory_collaboration_events_project_id_fkey FOREIGN KEY (project_id) REFERENCES memory_event_heads(project_id),
    CONSTRAINT memory_collaboration_events_resource_kind_check CHECK((MEMORY_ARRAY_CONTAINS(JSON_ARRAY(CAST('signal' AS TEXT), CAST('checkpoint' AS TEXT), CAST('bundle' AS TEXT), CAST('presence' AS TEXT), CAST('usage' AS TEXT)), resource_kind))),
    CONSTRAINT memory_collaboration_events_revision_check CHECK((revision > 0))
);
CREATE INDEX idx_collaboration_event_retention ON memory_collaboration_events(project_id, created_at, "position");

CREATE TABLE memory_continuity_bundles (
    id UUID TEXT COLLATE NOCASE NOT NULL DEFAULT (GEN_RANDOM_UUID()),
    project_id TEXT NOT NULL,
    source_handoff_id UUID TEXT COLLATE NOCASE,
    source_checkpoint_id UUID TEXT COLLATE NOCASE,
    from_user TEXT NOT NULL,
    classification TEXT NOT NULL,
    source_digest TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT (1),
    policy_version INTEGER NOT NULL,
    expires_at TIMESTAMPTZ TEXT NOT NULL,
    revoked_at TIMESTAMPTZ TEXT,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ TEXT NOT NULL DEFAULT (CLOCK_TIMESTAMP()),
    CONSTRAINT memory_continuity_bundles_check CHECK(((source_handoff_id IS NULL) <> (source_checkpoint_id IS NULL))),
    CONSTRAINT memory_continuity_bundles_id_project_id_key UNIQUE (id, project_id),
    CONSTRAINT memory_continuity_bundles_pkey PRIMARY KEY (id),
    CONSTRAINT memory_continuity_bundles_source_checkpoint_id_key UNIQUE (source_checkpoint_id),
    CONSTRAINT memory_continuity_bundles_source_checkpoint_id_project_id_fkey FOREIGN KEY (source_checkpoint_id, project_id) REFERENCES memory_checkpoints(id, project_id) ON DELETE RESTRICT,
    CONSTRAINT memory_continuity_bundles_source_handoff_id_key UNIQUE (source_handoff_id),
    CONSTRAINT memory_continuity_bundles_source_handoff_id_project_id_fkey FOREIGN KEY (source_handoff_id, project_id) REFERENCES handoffs(id, project_id) ON DELETE RESTRICT,
    CONSTRAINT memory_continuity_bundles_version_check CHECK((version > 0))
);

CREATE TABLE memory_continuity_claims (
    unit_id UUID TEXT COLLATE NOCASE NOT NULL,
    project_id TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    claim_token_digest TEXT NOT NULL,
    claim_generation INTEGER NOT NULL,
    created_at TIMESTAMPTZ TEXT NOT NULL DEFAULT (CLOCK_TIMESTAMP()),
    CONSTRAINT memory_continuity_claims_claim_generation_check CHECK((claim_generation > 0)),
    CONSTRAINT memory_continuity_claims_pkey PRIMARY KEY (unit_id, actor_id, claim_token_digest),
    CONSTRAINT memory_continuity_claims_unit_id_claim_generation_key UNIQUE (unit_id, claim_generation),
    CONSTRAINT memory_continuity_claims_unit_id_project_id_fkey FOREIGN KEY (unit_id, project_id) REFERENCES memory_continuity_units(id, project_id) ON DELETE RESTRICT
);

CREATE TABLE memory_continuity_deliveries (
    id UUID TEXT COLLATE NOCASE NOT NULL DEFAULT (GEN_RANDOM_UUID()),
    project_id TEXT NOT NULL,
    bundle_id UUID TEXT COLLATE NOCASE NOT NULL,
    recipient_user_id TEXT NOT NULL,
    routing_version INTEGER NOT NULL,
    acknowledged_at TIMESTAMPTZ TEXT,
    revoked_at TIMESTAMPTZ TEXT,
    created_at TIMESTAMPTZ TEXT NOT NULL DEFAULT (CLOCK_TIMESTAMP()),
    CONSTRAINT memory_continuity_deliveries_bundle_id_project_id_fkey FOREIGN KEY (bundle_id, project_id) REFERENCES memory_continuity_bundles(id, project_id) ON DELETE RESTRICT,
    CONSTRAINT memory_continuity_deliveries_id_project_id_key UNIQUE (id, project_id),
    CONSTRAINT memory_continuity_deliveries_pkey PRIMARY KEY (id)
);
CREATE INDEX idx_continuity_inbox ON memory_continuity_deliveries(project_id, recipient_user_id, created_at DESC, id DESC);
CREATE UNIQUE INDEX uq_continuity_active_delivery ON memory_continuity_deliveries(bundle_id, recipient_user_id) WHERE (revoked_at IS NULL);

CREATE TABLE memory_continuity_events (
    id UUID TEXT COLLATE NOCASE NOT NULL DEFAULT (GEN_RANDOM_UUID()),
    project_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    action TEXT NOT NULL,
    details JSONB TEXT NOT NULL,
    created_at TIMESTAMPTZ TEXT NOT NULL DEFAULT (CLOCK_TIMESTAMP()),
    CONSTRAINT memory_continuity_events_pkey PRIMARY KEY (id)
);
CREATE INDEX idx_continuity_events ON memory_continuity_events(project_id, created_at DESC, id DESC);
