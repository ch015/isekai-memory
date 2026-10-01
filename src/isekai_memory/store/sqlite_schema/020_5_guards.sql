-- Immutable history and anti-replay guards, matching PostgreSQL 005–012.

CREATE TRIGGER guard_memory_continuity_events_update BEFORE UPDATE ON memory_continuity_events
WHEN 1
BEGIN
    SELECT RAISE(ABORT, 'guard_memory_continuity_events_update: immutable history or invalid transition');
END;

CREATE TRIGGER guard_memory_continuity_events_delete BEFORE DELETE ON memory_continuity_events
WHEN 1
BEGIN
    SELECT RAISE(ABORT, 'guard_memory_continuity_events_delete: immutable history or invalid transition');
END;

CREATE TRIGGER guard_memory_continuity_receipts_update BEFORE UPDATE ON memory_continuity_receipts
WHEN 1
BEGIN
    SELECT RAISE(ABORT, 'guard_memory_continuity_receipts_update: immutable history or invalid transition');
END;

CREATE TRIGGER guard_memory_continuity_receipts_delete BEFORE DELETE ON memory_continuity_receipts
WHEN 1
BEGIN
    SELECT RAISE(ABORT, 'guard_memory_continuity_receipts_delete: immutable history or invalid transition');
END;

CREATE TRIGGER guard_memory_continuity_claims_update BEFORE UPDATE ON memory_continuity_claims
WHEN 1
BEGIN
    SELECT RAISE(ABORT, 'guard_memory_continuity_claims_update: immutable history or invalid transition');
END;

CREATE TRIGGER guard_memory_continuity_claims_delete BEFORE DELETE ON memory_continuity_claims
WHEN 1
BEGIN
    SELECT RAISE(ABORT, 'guard_memory_continuity_claims_delete: immutable history or invalid transition');
END;

CREATE TRIGGER guard_memory_skill_sources_update BEFORE UPDATE ON memory_skill_sources
WHEN 1
BEGIN
    SELECT RAISE(ABORT, 'guard_memory_skill_sources_update: immutable history or invalid transition');
END;

CREATE TRIGGER guard_memory_skill_sources_delete BEFORE DELETE ON memory_skill_sources
WHEN 1
BEGIN
    SELECT RAISE(ABORT, 'guard_memory_skill_sources_delete: immutable history or invalid transition');
END;

CREATE TRIGGER guard_memory_knowledge_events_update BEFORE UPDATE ON memory_knowledge_events
WHEN 1
BEGIN
    SELECT RAISE(ABORT, 'guard_memory_knowledge_events_update: immutable history or invalid transition');
END;

CREATE TRIGGER guard_memory_knowledge_events_delete BEFORE DELETE ON memory_knowledge_events
WHEN 1
BEGIN
    SELECT RAISE(ABORT, 'guard_memory_knowledge_events_delete: immutable history or invalid transition');
END;

CREATE TRIGGER guard_memory_asset_feedback_update BEFORE UPDATE ON memory_asset_feedback
WHEN 1
BEGIN
    SELECT RAISE(ABORT, 'guard_memory_asset_feedback_update: immutable history or invalid transition');
END;

CREATE TRIGGER guard_memory_asset_feedback_delete BEFORE DELETE ON memory_asset_feedback
WHEN 1
BEGIN
    SELECT RAISE(ABORT, 'guard_memory_asset_feedback_delete: immutable history or invalid transition');
END;

CREATE TRIGGER guard_memory_usage_receipts_update BEFORE UPDATE ON memory_usage_receipts
WHEN 1
BEGIN
    SELECT RAISE(ABORT, 'guard_memory_usage_receipts_update: immutable history or invalid transition');
END;

CREATE TRIGGER guard_memory_usage_receipts_delete BEFORE DELETE ON memory_usage_receipts
WHEN 1
BEGIN
    SELECT RAISE(ABORT, 'guard_memory_usage_receipts_delete: immutable history or invalid transition');
END;

CREATE TRIGGER guard_managed_handoff_update BEFORE UPDATE ON handoffs
WHEN OLD.continuity_managed
BEGIN
    SELECT RAISE(ABORT, 'guard_managed_handoff_update: immutable history or invalid transition');
END;

CREATE TRIGGER guard_managed_handoff_delete BEFORE DELETE ON handoffs
WHEN OLD.continuity_managed
BEGIN
    SELECT RAISE(ABORT, 'guard_managed_handoff_delete: immutable history or invalid transition');
END;

CREATE TRIGGER guard_checkpoint_update BEFORE UPDATE ON memory_checkpoints
WHEN OLD.forgotten_at IS NOT NULL OR NEW.forgotten_at IS NULL OR NEW.continuation!='{}' OR NEW.snapshot IS NOT NULL OR NEW.id IS NOT OLD.id OR
        NEW.project_id IS NOT OLD.project_id OR
        NEW.work_id IS NOT OLD.work_id OR
        NEW.from_user IS NOT OLD.from_user OR
        NEW.version IS NOT OLD.version OR
        NEW.classification IS NOT OLD.classification OR
        NEW.lock_snapshot_digest IS NOT OLD.lock_snapshot_digest OR
        NEW.continuation_digest IS NOT OLD.continuation_digest OR
        NEW.snapshot_digest IS NOT OLD.snapshot_digest OR
        NEW.payload_digest IS NOT OLD.payload_digest OR
        NEW.policy_version IS NOT OLD.policy_version OR
        NEW.expires_at IS NOT OLD.expires_at OR
        NEW.created_at IS NOT OLD.created_at
BEGIN
    SELECT RAISE(ABORT, 'guard_checkpoint_update: immutable history or invalid transition');
END;

CREATE TRIGGER guard_checkpoint_delete BEFORE DELETE ON memory_checkpoints
WHEN 1
BEGIN
    SELECT RAISE(ABORT, 'guard_checkpoint_delete: immutable history or invalid transition');
END;

CREATE TRIGGER guard_experience_identity BEFORE UPDATE ON memory_experiences
WHEN NEW.kind IS NOT OLD.kind OR
        NEW.source_lock_digest IS NOT OLD.source_lock_digest OR
        NEW.source_payload_digest IS NOT OLD.source_payload_digest OR
        NEW.content_fingerprint IS NOT OLD.content_fingerprint OR
        NEW.classification IS NOT OLD.classification OR
        NEW.supersedes_id IS NOT OLD.supersedes_id OR
        NEW.supersedes_version IS NOT OLD.supersedes_version OR
        NEW.revision_root_id IS NOT OLD.revision_root_id OR
        NEW.revision_number IS NOT OLD.revision_number OR
        NEW.is_correction IS NOT OLD.is_correction OR
        NEW.submission_digest IS NOT OLD.submission_digest OR
        NEW.idempotency_key IS NOT OLD.idempotency_key OR
        NEW.created_by IS NOT OLD.created_by OR
        NEW.created_at IS NOT OLD.created_at
BEGIN
    SELECT RAISE(ABORT, 'guard_experience_identity: immutable history or invalid transition');
END;

CREATE TRIGGER guard_experience_content BEFORE UPDATE ON memory_experiences
WHEN (NEW.status!='forgotten' OR OLD.status='forgotten') AND (NEW.title IS NOT OLD.title OR
        NEW.content IS NOT OLD.content OR
        NEW.tags IS NOT OLD.tags OR
        NEW.search_text IS NOT OLD.search_text OR
        NEW.source IS NOT OLD.source OR
        NEW.source_handoff_id IS NOT OLD.source_handoff_id)
BEGIN
    SELECT RAISE(ABORT, 'guard_experience_content: immutable history or invalid transition');
END;

CREATE TRIGGER guard_skill_revision BEFORE UPDATE ON memory_skill_revisions
WHEN (NEW.id IS NOT OLD.id OR
        NEW.skill_id IS NOT OLD.skill_id OR
        NEW.project_id IS NOT OLD.project_id OR
        NEW.revision IS NOT OLD.revision OR
        NEW.base_active_revision IS NOT OLD.base_active_revision OR
        NEW.origin IS NOT OLD.origin OR
        NEW.classification IS NOT OLD.classification OR
        NEW.source_lock_digest IS NOT OLD.source_lock_digest OR
        NEW.source_watermark IS NOT OLD.source_watermark OR
        NEW.content_digest IS NOT OLD.content_digest OR
        NEW.created_by IS NOT OLD.created_by OR
        NEW.idempotency_key IS NOT OLD.idempotency_key OR
        NEW.submission_digest IS NOT OLD.submission_digest OR
        NEW.created_at IS NOT OLD.created_at) OR (NEW.body IS NOT OLD.body AND NOT (NEW.status='forgotten' AND NEW.body='{}')) OR (OLD.status='forgotten' AND NEW.status!='forgotten') OR (OLD.approved_at IS NOT NULL AND NEW.approved_at IS NOT OLD.approved_at)
BEGIN
    SELECT RAISE(ABORT, 'guard_skill_revision: immutable history or invalid transition');
END;

CREATE TRIGGER guard_asset_grant_update BEFORE UPDATE ON memory_asset_grants
WHEN NEW.id IS NOT OLD.id OR
        NEW.project_id IS NOT OLD.project_id OR
        NEW.consumer_project_id IS NOT OLD.consumer_project_id OR
        NEW.asset_kind IS NOT OLD.asset_kind OR
        NEW.asset_id IS NOT OLD.asset_id OR
        NEW.asset_version IS NOT OLD.asset_version OR
        NEW.asset_digest IS NOT OLD.asset_digest OR
        NEW.classification IS NOT OLD.classification OR
        NEW.expires_at IS NOT OLD.expires_at OR
        NEW.created_by IS NOT OLD.created_by OR
        NEW.idempotency_key IS NOT OLD.idempotency_key OR
        NEW.submission_digest IS NOT OLD.submission_digest OR
        NEW.created_at IS NOT OLD.created_at OR OLD.version!=1 OR NEW.version!=2
BEGIN
    SELECT RAISE(ABORT, 'guard_asset_grant_update: immutable history or invalid transition');
END;

CREATE TRIGGER guard_asset_grant_delete BEFORE DELETE ON memory_asset_grants
WHEN 1
BEGIN
    SELECT RAISE(ABORT, 'guard_asset_grant_delete: immutable history or invalid transition');
END;

CREATE TRIGGER guard_skill_import_update BEFORE UPDATE ON memory_skill_imports
WHEN NEW.id IS NOT OLD.id OR
        NEW.project_id IS NOT OLD.project_id OR
        NEW.origin_key IS NOT OLD.origin_key OR
        NEW.archive_digest IS NOT OLD.archive_digest OR
        NEW.artifact_digest IS NOT OLD.artifact_digest OR
        NEW.manifest_digest IS NOT OLD.manifest_digest OR
        NEW.classification IS NOT OLD.classification OR
        NEW.created_by IS NOT OLD.created_by OR
        NEW.idempotency_key IS NOT OLD.idempotency_key OR
        NEW.submission_digest IS NOT OLD.submission_digest OR
        NEW.created_at IS NOT OLD.created_at OR OLD.status!='quarantined' OR NEW.status!='forgotten'
BEGIN
    SELECT RAISE(ABORT, 'guard_skill_import_update: immutable history or invalid transition');
END;

CREATE TRIGGER guard_skill_import_delete BEFORE DELETE ON memory_skill_imports
WHEN 1
BEGIN
    SELECT RAISE(ABORT, 'guard_skill_import_delete: immutable history or invalid transition');
END;

CREATE TRIGGER guard_presence_identity BEFORE UPDATE ON memory_presence_sessions
WHEN NEW.id IS NOT OLD.id OR
        NEW.project_id IS NOT OLD.project_id OR
        NEW.actor_id IS NOT OLD.actor_id OR
        NEW.client_instance_id IS NOT OLD.client_instance_id OR
        NEW.session_token_digest IS NOT OLD.session_token_digest OR
        NEW.register_digest IS NOT OLD.register_digest OR
        NEW.session_kind IS NOT OLD.session_kind OR
        NEW.parent_session_id IS NOT OLD.parent_session_id OR
        NEW.created_at IS NOT OLD.created_at
BEGIN
    SELECT RAISE(ABORT, 'guard_presence_identity: immutable history or invalid transition');
END;

CREATE TRIGGER guard_presence_state BEFORE UPDATE ON memory_presence_sessions
WHEN OLD.retired_at IS NOT NULL OR NEW.sequence<OLD.sequence OR NEW.state_sequence<OLD.state_sequence OR (OLD.ended_at IS NOT NULL AND NEW.ended_at IS NOT OLD.ended_at) OR (OLD.ended_at IS NOT NULL AND NEW.retired_at IS NULL AND (NEW.id IS NOT OLD.id OR
        NEW.project_id IS NOT OLD.project_id OR
        NEW.actor_id IS NOT OLD.actor_id OR
        NEW.client_instance_id IS NOT OLD.client_instance_id OR
        NEW.session_token_digest IS NOT OLD.session_token_digest OR
        NEW.register_digest IS NOT OLD.register_digest OR
        NEW.host_kind IS NOT OLD.host_kind OR
        NEW.session_kind IS NOT OLD.session_kind OR
        NEW.parent_session_id IS NOT OLD.parent_session_id OR
        NEW.classification IS NOT OLD.classification OR
        NEW.sequence IS NOT OLD.sequence OR
        NEW.state_sequence IS NOT OLD.state_sequence OR
        NEW.report_digest IS NOT OLD.report_digest OR
        NEW.reported_policy_version IS NOT OLD.reported_policy_version OR
        NEW.reported_state IS NOT OLD.reported_state OR
        NEW.observation_scope IS NOT OLD.observation_scope OR
        NEW.state_observation_available IS NOT OLD.state_observation_available OR
        NEW.active_work_count IS NOT OLD.active_work_count OR
        NEW.work_unit_id IS NOT OLD.work_unit_id OR
        NEW.checkpoint_id IS NOT OLD.checkpoint_id OR
        NEW.created_at IS NOT OLD.created_at OR
        NEW.last_seen_at IS NOT OLD.last_seen_at OR
        NEW.state_since_at IS NOT OLD.state_since_at OR
        NEW.idle_since_at IS NOT OLD.idle_since_at OR
        NEW.ended_at IS NOT OLD.ended_at OR
        NEW.retired_at IS NOT OLD.retired_at)) OR instr('public,internal,confidential,restricted',NEW.classification)<instr('public,internal,confidential,restricted',OLD.classification)
BEGIN
    SELECT RAISE(ABORT, 'guard_presence_state: immutable history or invalid transition');
END;

CREATE TRIGGER guard_presence_delete BEFORE DELETE ON memory_presence_sessions
WHEN 1
BEGIN
    SELECT RAISE(ABORT, 'guard_presence_delete: immutable history or invalid transition');
END;

CREATE TRIGGER guard_usage_identity BEFORE UPDATE ON memory_usage_sessions
WHEN NEW.id IS NOT OLD.id OR
        NEW.project_id IS NOT OLD.project_id OR
        NEW.actor_id IS NOT OLD.actor_id OR
        NEW.execution_attempt_id IS NOT OLD.execution_attempt_id OR
        NEW.meter_epoch IS NOT OLD.meter_epoch OR
        NEW.session_token_digest IS NOT OLD.session_token_digest OR
        NEW.register_digest IS NOT OLD.register_digest OR
        NEW.classification IS NOT OLD.classification OR
        NEW.parent_session_id IS NOT OLD.parent_session_id OR
        NEW.work_unit_id IS NOT OLD.work_unit_id OR
        NEW.claim_generation IS NOT OLD.claim_generation OR
        NEW.created_at IS NOT OLD.created_at OR
        NEW.accepts_until IS NOT OLD.accepts_until
BEGIN
    SELECT RAISE(ABORT, 'guard_usage_identity: immutable history or invalid transition');
END;

CREATE TRIGGER guard_usage_state BEFORE UPDATE ON memory_usage_sessions
WHEN OLD.retired_at IS NOT NULL OR NEW.sequence<OLD.sequence OR (OLD.first_received_at IS NOT NULL AND NEW.first_received_at IS NOT OLD.first_received_at) OR (OLD.finalized_at IS NOT NULL AND (NEW.finalized_at IS NOT OLD.finalized_at OR NEW.bucket_at IS NOT OLD.bucket_at OR NEW.completion_state IS NOT OLD.completion_state)) OR (NEW.retired_at IS NULL AND (NEW.host_kind IS NOT OLD.host_kind OR
        NEW.host_version IS NOT OLD.host_version OR
        NEW.adapter_version IS NOT OLD.adapter_version OR
        NEW.provider IS NOT OLD.provider OR
        NEW.model_id IS NOT OLD.model_id))
BEGIN
    SELECT RAISE(ABORT, 'guard_usage_state: immutable history or invalid transition');
END;

CREATE TRIGGER guard_usage_delete BEFORE DELETE ON memory_usage_sessions
WHEN 1
BEGIN
    SELECT RAISE(ABORT, 'guard_usage_delete: immutable history or invalid transition');
END;
