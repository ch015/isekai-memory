"""Independent 1:N delivery, administrator policy and recoverable checkpoints.

Revision ID: 010
Revises: 009
"""

from alembic import op

revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        ALTER TABLE handoffs ADD COLUMN continuity_managed boolean NOT NULL DEFAULT false;
        CREATE FUNCTION guard_managed_handoff() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.continuity_managed THEN
                RAISE EXCEPTION 'Managed continuity source is immutable; use recipient delivery APIs';
            END IF;
            IF TG_OP='DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER guard_managed_handoff BEFORE UPDATE OR DELETE ON handoffs
            FOR EACH ROW EXECUTE FUNCTION guard_managed_handoff();
        CREATE TABLE memory_continuity_policies (
            project_id text PRIMARY KEY, version integer NOT NULL CHECK(version>0),
            policy jsonb NOT NULL CHECK(jsonb_typeof(policy)='object'),
            updated_by text NOT NULL, updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
        );
        CREATE TABLE memory_checkpoints (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(), project_id text NOT NULL,
            work_id text NOT NULL, from_user text NOT NULL, version integer NOT NULL CHECK(version>0),
            classification text NOT NULL CHECK(classification IN ('public','internal','confidential','restricted')),
            lock_snapshot_digest text NOT NULL, continuation jsonb NOT NULL, continuation_digest text NOT NULL,
            snapshot jsonb, snapshot_digest text, payload_digest text NOT NULL,
            policy_version integer NOT NULL, expires_at timestamptz NOT NULL,
            forgotten_at timestamptz, created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            UNIQUE(project_id,from_user,work_id,version), UNIQUE(id,project_id),
            CHECK((snapshot IS NULL) = (snapshot_digest IS NULL) OR forgotten_at IS NOT NULL)
        );
        CREATE INDEX idx_checkpoints_project ON memory_checkpoints(project_id,created_at DESC,id DESC);
        CREATE TABLE memory_continuity_bundles (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(), project_id text NOT NULL,
            source_handoff_id uuid, source_checkpoint_id uuid, from_user text NOT NULL,
            classification text NOT NULL, source_digest text NOT NULL,
            version integer NOT NULL DEFAULT 1 CHECK(version>0), policy_version integer NOT NULL,
            expires_at timestamptz NOT NULL, revoked_at timestamptz,
            created_by text NOT NULL, created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            UNIQUE(id,project_id), UNIQUE(source_handoff_id), UNIQUE(source_checkpoint_id),
            FOREIGN KEY(source_handoff_id,project_id) REFERENCES handoffs(id,project_id) ON DELETE RESTRICT,
            FOREIGN KEY(source_checkpoint_id,project_id) REFERENCES memory_checkpoints(id,project_id) ON DELETE RESTRICT,
            CHECK((source_handoff_id IS NULL) != (source_checkpoint_id IS NULL))
        );
        CREATE TABLE memory_continuity_deliveries (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(), project_id text NOT NULL, bundle_id uuid NOT NULL,
            recipient_user_id text NOT NULL, routing_version integer NOT NULL,
            acknowledged_at timestamptz, revoked_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(), UNIQUE(id,project_id),
            FOREIGN KEY(bundle_id,project_id) REFERENCES memory_continuity_bundles(id,project_id) ON DELETE RESTRICT
        );
        CREATE UNIQUE INDEX uq_continuity_active_delivery ON memory_continuity_deliveries(bundle_id,recipient_user_id)
            WHERE revoked_at IS NULL;
        CREATE INDEX idx_continuity_inbox ON memory_continuity_deliveries(project_id,recipient_user_id,created_at DESC,id DESC);
        CREATE TABLE memory_continuity_units (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(), project_id text NOT NULL, bundle_id uuid NOT NULL,
            unit_key text NOT NULL, summary text NOT NULL, assignee_user_ids text[] NOT NULL,
            state text NOT NULL DEFAULT 'available' CHECK(state IN ('available','claimed','completed','cancelled')),
            claimed_by text, claim_token_digest text, claim_generation integer NOT NULL DEFAULT 0 CHECK(claim_generation>=0),
            lease_expires_at timestamptz, updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            UNIQUE(bundle_id,unit_key), UNIQUE(id,project_id),
            FOREIGN KEY(bundle_id,project_id) REFERENCES memory_continuity_bundles(id,project_id) ON DELETE RESTRICT,
            CHECK(cardinality(assignee_user_ids) BETWEEN 1 AND 32),
            CHECK(state!='claimed' OR (claimed_by IS NOT NULL AND claim_token_digest IS NOT NULL AND lease_expires_at IS NOT NULL))
        );
        CREATE TABLE memory_continuity_events (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(), project_id text NOT NULL, target_id text NOT NULL,
            actor_id text NOT NULL, action text NOT NULL, details jsonb NOT NULL,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp()
        );
        CREATE INDEX idx_continuity_events ON memory_continuity_events(project_id,created_at DESC,id DESC);
        CREATE TABLE memory_continuity_claims (
            unit_id uuid NOT NULL, project_id text NOT NULL, actor_id text NOT NULL, claim_token_digest text NOT NULL,
            claim_generation integer NOT NULL CHECK(claim_generation>0),
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            PRIMARY KEY(unit_id,actor_id,claim_token_digest), UNIQUE(unit_id,claim_generation),
            FOREIGN KEY(unit_id,project_id) REFERENCES memory_continuity_units(id,project_id) ON DELETE RESTRICT
        );
        CREATE TABLE memory_continuity_receipts (
            project_id text NOT NULL, actor_id text NOT NULL, operation text NOT NULL, idempotency_key text NOT NULL,
            request_digest text NOT NULL, result jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            PRIMARY KEY(project_id,actor_id,operation,idempotency_key)
        );
        CREATE FUNCTION guard_continuity_receipt() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'Continuity receipts and events are immutable'; END $$;
        CREATE TRIGGER guard_continuity_event BEFORE UPDATE OR DELETE ON memory_continuity_events
            FOR EACH ROW EXECUTE FUNCTION guard_continuity_receipt();
        CREATE TRIGGER guard_continuity_receipt BEFORE UPDATE OR DELETE ON memory_continuity_receipts
            FOR EACH ROW EXECUTE FUNCTION guard_continuity_receipt();
        CREATE TRIGGER guard_continuity_claim BEFORE UPDATE OR DELETE ON memory_continuity_claims
            FOR EACH ROW EXECUTE FUNCTION guard_continuity_receipt();
        CREATE FUNCTION guard_continuity_checkpoint() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Checkpoint provenance cannot be deleted'; END IF;
            IF OLD.forgotten_at IS NOT NULL OR NEW.forgotten_at IS NULL OR NEW.continuation!='{}'::jsonb
               OR NEW.snapshot IS NOT NULL OR
               (to_jsonb(NEW)-ARRAY['continuation','snapshot','forgotten_at']) IS DISTINCT FROM
               (to_jsonb(OLD)-ARRAY['continuation','snapshot','forgotten_at']) THEN
                RAISE EXCEPTION 'Checkpoints are immutable except explicit body erasure';
            END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER guard_continuity_checkpoint BEFORE UPDATE OR DELETE ON memory_checkpoints
            FOR EACH ROW EXECUTE FUNCTION guard_continuity_checkpoint();
    """)


def downgrade():
    op.execute("""
        LOCK TABLE handoffs, memory_continuity_policies, memory_checkpoints, memory_continuity_bundles,
            memory_continuity_deliveries, memory_continuity_units, memory_continuity_events,
            memory_continuity_receipts, memory_continuity_claims IN ACCESS EXCLUSIVE MODE;
        DO $$ BEGIN
            IF EXISTS(SELECT 1 FROM memory_continuity_policies) OR EXISTS(SELECT 1 FROM memory_checkpoints)
                OR EXISTS(SELECT 1 FROM memory_continuity_bundles) OR EXISTS(SELECT 1 FROM memory_continuity_events)
                OR EXISTS(SELECT 1 FROM memory_continuity_receipts) OR EXISTS(SELECT 1 FROM handoffs WHERE continuity_managed)
            THEN RAISE EXCEPTION '010 downgrade refused: continuity history exists'; END IF;
        END $$;
        DROP TABLE memory_continuity_receipts, memory_continuity_events, memory_continuity_claims, memory_continuity_units,
            memory_continuity_deliveries, memory_continuity_bundles, memory_checkpoints, memory_continuity_policies;
        DROP FUNCTION guard_continuity_receipt(), guard_continuity_checkpoint();
        DROP TRIGGER guard_managed_handoff ON handoffs;
        DROP FUNCTION guard_managed_handoff();
        ALTER TABLE handoffs DROP COLUMN continuity_managed;
    """)
