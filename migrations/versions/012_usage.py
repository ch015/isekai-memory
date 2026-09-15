"""Independent opt-in usage policy and absolute-counter receipt ledger."""
from alembic import op

revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE memory_usage_policies (
            project_id text PRIMARY KEY, version integer NOT NULL CHECK(version>0),
            policy jsonb NOT NULL CHECK(jsonb_typeof(policy)='object'),
            updated_by text NOT NULL, updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
        );
        CREATE TABLE memory_usage_sessions (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(), project_id text NOT NULL, actor_id text NOT NULL,
            execution_attempt_id uuid NOT NULL, meter_epoch uuid NOT NULL,
            session_token_digest text NOT NULL, register_digest text NOT NULL,
            host_kind text NOT NULL CHECK(host_kind IN ('codex','claude','kiro','unknown')),
            host_version text NOT NULL, adapter_version text NOT NULL, provider text NOT NULL, model_id text NOT NULL,
            classification text NOT NULL CHECK(classification IN ('public','internal','confidential','restricted')),
            parent_session_id uuid, work_unit_id uuid, claim_generation integer,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(), accepts_until timestamptz NOT NULL,
            sequence integer NOT NULL DEFAULT 0 CHECK(sequence>=0), metrics jsonb,
            coverage text NOT NULL DEFAULT 'partial' CHECK(coverage IN ('partial','complete')),
            completion_state text NOT NULL DEFAULT 'in_progress' CHECK(completion_state IN ('in_progress','final')),
            first_received_at timestamptz, last_received_at timestamptz,
            bucket_at timestamptz, bucket_basis text CHECK(bucket_basis IN ('source_reported','server_first_received','provisional')),
            source_occurred_at timestamptz, finalized_at timestamptz, retired_at timestamptz,
            UNIQUE(project_id,actor_id,execution_attempt_id), UNIQUE(id,project_id),
            FOREIGN KEY(parent_session_id,project_id) REFERENCES memory_usage_sessions(id,project_id) ON DELETE RESTRICT,
            FOREIGN KEY(work_unit_id,project_id) REFERENCES memory_continuity_units(id,project_id) ON DELETE RESTRICT,
            CHECK((work_unit_id IS NULL)=(claim_generation IS NULL)),
            CHECK(accepts_until>created_at)
        );
        CREATE INDEX idx_usage_actor ON memory_usage_sessions(project_id,actor_id,created_at DESC,id DESC);
        CREATE INDEX idx_usage_bucket ON memory_usage_sessions(project_id,bucket_at,actor_id) WHERE retired_at IS NULL;
        CREATE TABLE memory_usage_receipts (
            session_id uuid NOT NULL REFERENCES memory_usage_sessions(id) ON DELETE RESTRICT,
            project_id text NOT NULL, sequence integer NOT NULL CHECK(sequence>0), request_digest text NOT NULL,
            received_at timestamptz NOT NULL, bucket_at timestamptz NOT NULL,
            completion_state text NOT NULL, PRIMARY KEY(session_id,sequence),
            FOREIGN KEY(session_id,project_id) REFERENCES memory_usage_sessions(id,project_id) ON DELETE RESTRICT
        );
        CREATE INDEX idx_usage_receipt_rate ON memory_usage_receipts(project_id,received_at);
        CREATE FUNCTION guard_usage_session() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Usage anti-replay identities cannot be deleted'; END IF;
            IF (to_jsonb(NEW)-ARRAY['host_kind','host_version','adapter_version','provider','model_id','metrics',
                'coverage','completion_state','sequence','first_received_at','last_received_at','bucket_at','bucket_basis',
                'source_occurred_at','finalized_at','retired_at']) IS DISTINCT FROM
               (to_jsonb(OLD)-ARRAY['host_kind','host_version','adapter_version','provider','model_id','metrics',
                'coverage','completion_state','sequence','first_received_at','last_received_at','bucket_at','bucket_basis',
                'source_occurred_at','finalized_at','retired_at']) THEN
                RAISE EXCEPTION 'Usage ownership and attempt binding are immutable';
            END IF;
            IF OLD.retired_at IS NOT NULL OR NEW.sequence<OLD.sequence
                OR (OLD.first_received_at IS NOT NULL AND NEW.first_received_at IS DISTINCT FROM OLD.first_received_at)
                OR (OLD.finalized_at IS NOT NULL AND
                    (NEW.finalized_at IS DISTINCT FROM OLD.finalized_at OR NEW.bucket_at IS DISTINCT FROM OLD.bucket_at
                     OR NEW.completion_state IS DISTINCT FROM OLD.completion_state)) THEN
                RAISE EXCEPTION 'Usage receipt/finalization/retirement cannot regress';
            END IF;
            IF NEW.retired_at IS NULL AND
               ROW(NEW.host_kind,NEW.host_version,NEW.adapter_version,NEW.provider,NEW.model_id) IS DISTINCT FROM
               ROW(OLD.host_kind,OLD.host_version,OLD.adapter_version,OLD.provider,OLD.model_id) THEN
                RAISE EXCEPTION 'Usage source metadata is immutable until retirement';
            END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER guard_usage_session BEFORE UPDATE OR DELETE ON memory_usage_sessions
            FOR EACH ROW EXECUTE FUNCTION guard_usage_session();
        CREATE FUNCTION guard_usage_receipt() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'Usage receipts are immutable'; END $$;
        CREATE TRIGGER guard_usage_receipt BEFORE UPDATE OR DELETE ON memory_usage_receipts
            FOR EACH ROW EXECUTE FUNCTION guard_usage_receipt();
    """)


def downgrade():
    op.execute("""
        LOCK TABLE memory_usage_receipts,memory_usage_sessions,memory_usage_policies IN ACCESS EXCLUSIVE MODE;
        DO $$ BEGIN
            IF EXISTS(SELECT 1 FROM memory_usage_sessions) OR EXISTS(SELECT 1 FROM memory_usage_policies)
            THEN RAISE EXCEPTION '012 downgrade refused: usage/anti-replay history exists'; END IF;
        END $$;
        DROP TABLE memory_usage_receipts,memory_usage_sessions,memory_usage_policies;
        DROP FUNCTION guard_usage_session(),guard_usage_receipt();
    """)
