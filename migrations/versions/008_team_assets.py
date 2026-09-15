"""Explicit revocable sharing, pushed knowledge, quarantined exchange and feedback.

Revision ID: 008
Revises: 007
"""

from alembic import op

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE memory_asset_grants (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            project_id text NOT NULL, consumer_project_id text NOT NULL,
            asset_kind text NOT NULL CHECK (asset_kind IN ('experience','skill','knowledge')),
            asset_id uuid NOT NULL, asset_version integer NOT NULL CHECK (asset_version > 0),
            asset_digest text NOT NULL, classification text NOT NULL,
            expires_at timestamptz NOT NULL,
            version integer NOT NULL DEFAULT 1 CHECK (version IN (1,2)),
            revoked_at timestamptz, revoked_by text,
            created_by text NOT NULL, idempotency_key text NOT NULL, submission_digest text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            UNIQUE (project_id,created_by,idempotency_key),
            CHECK (project_id != consumer_project_id),
            CHECK ((version=1 AND revoked_at IS NULL AND revoked_by IS NULL)
                OR (version=2 AND revoked_at IS NOT NULL AND revoked_by IS NOT NULL))
        );
        CREATE INDEX idx_asset_grants_owner ON memory_asset_grants(project_id,created_at DESC,id DESC);
        CREATE TABLE memory_knowledge_documents (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(), project_id text NOT NULL,
            provider text NOT NULL CHECK (provider='pushed_wiki_v1'), source_key text NOT NULL,
            source_revision text NOT NULL, version integer NOT NULL CHECK (version > 0),
            classification text NOT NULL CHECK (classification IN ('public','internal','confidential','restricted')),
            title text NOT NULL, content text NOT NULL, content_digest text NOT NULL,
            status text NOT NULL CHECK (status IN ('active','deleted')), valid_until timestamptz NOT NULL,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(), updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            UNIQUE (project_id,provider,source_key), UNIQUE (id,project_id),
            CHECK ((status='deleted' AND title='' AND content='') OR
                (status='active' AND length(title) BETWEEN 1 AND 200 AND length(content) BETWEEN 1 AND 8192))
        );
        CREATE INDEX idx_knowledge_project ON memory_knowledge_documents(project_id,created_at DESC,id DESC);
        CREATE TABLE memory_knowledge_events (
            document_id uuid NOT NULL REFERENCES memory_knowledge_documents(id) ON DELETE RESTRICT,
            version integer NOT NULL, actor_id text NOT NULL, action text NOT NULL CHECK (action IN ('sync','delete')),
            source_revision text, submission_digest text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            PRIMARY KEY (document_id,version), UNIQUE (document_id,source_revision)
        );
        CREATE TABLE memory_skill_imports (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(), project_id text NOT NULL,
            origin_key text NOT NULL, archive_digest text NOT NULL, artifact_digest text NOT NULL, manifest_digest text NOT NULL,
            classification text NOT NULL CHECK (classification IN ('public','internal','confidential','restricted')),
            payload jsonb NOT NULL, status text NOT NULL DEFAULT 'quarantined' CHECK (status IN ('quarantined','forgotten')),
            version integer NOT NULL DEFAULT 1 CHECK (version IN (1,2)),
            created_by text NOT NULL, idempotency_key text NOT NULL, submission_digest text NOT NULL,
            forgotten_by text, created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            UNIQUE (project_id,origin_key), UNIQUE (project_id,created_by,idempotency_key),
            CHECK ((status='quarantined' AND version=1 AND payload!='{}'::jsonb AND forgotten_by IS NULL)
                OR (status='forgotten' AND version=2 AND payload='{}'::jsonb AND forgotten_by IS NOT NULL))
        );
        CREATE TABLE memory_asset_feedback (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(), project_id text NOT NULL, actor_id text NOT NULL,
            asset_kind text NOT NULL CHECK (asset_kind IN ('experience','skill','knowledge')),
            asset_id uuid NOT NULL, asset_version integer NOT NULL CHECK (asset_version > 0),
            asset_digest text NOT NULL, owner_project_id text NOT NULL, grant_id uuid REFERENCES memory_asset_grants(id),
            usefulness text NOT NULL CHECK (usefulness IN ('helpful','not_helpful','uncertain')),
            outcome text NOT NULL CHECK (outcome IN ('not_attempted','succeeded','failed')),
            handoff_id uuid, evidence_digest text,
            idempotency_key text NOT NULL, submission_digest text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            UNIQUE (project_id,actor_id,idempotency_key),
            UNIQUE (project_id,actor_id,asset_kind,asset_id,asset_version),
            FOREIGN KEY (handoff_id,project_id) REFERENCES handoffs(id,project_id) ON DELETE RESTRICT,
            CHECK ((outcome='not_attempted' AND handoff_id IS NULL AND evidence_digest IS NULL)
                OR (outcome!='not_attempted' AND handoff_id IS NOT NULL AND evidence_digest IS NOT NULL))
        );
        CREATE INDEX idx_imports_project ON memory_skill_imports(project_id,status,created_at DESC,id DESC);
        CREATE INDEX idx_feedback_project ON memory_asset_feedback(project_id,created_at DESC,id DESC);
        CREATE FUNCTION guard_team_receipt() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'Team asset receipts are immutable'; END $$;
        CREATE TRIGGER guard_knowledge_event BEFORE UPDATE OR DELETE ON memory_knowledge_events
            FOR EACH ROW EXECUTE FUNCTION guard_team_receipt();
        CREATE TRIGGER guard_asset_feedback BEFORE UPDATE OR DELETE ON memory_asset_feedback
            FOR EACH ROW EXECUTE FUNCTION guard_team_receipt();
        CREATE FUNCTION guard_asset_grant() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Grant receipts cannot be deleted'; END IF;
            IF (to_jsonb(NEW)-ARRAY['version','revoked_at','revoked_by']) IS DISTINCT FROM
               (to_jsonb(OLD)-ARRAY['version','revoked_at','revoked_by']) OR OLD.version!=1 OR NEW.version!=2 THEN
                RAISE EXCEPTION 'Only permanent grant revocation is allowed';
            END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER guard_asset_grant BEFORE UPDATE OR DELETE ON memory_asset_grants
            FOR EACH ROW EXECUTE FUNCTION guard_asset_grant();
        CREATE FUNCTION guard_skill_import() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Import receipts cannot be deleted'; END IF;
            IF (to_jsonb(NEW)-ARRAY['version','status','payload','forgotten_by']) IS DISTINCT FROM
               (to_jsonb(OLD)-ARRAY['version','status','payload','forgotten_by']) OR
               OLD.status!='quarantined' OR NEW.status!='forgotten' THEN
                RAISE EXCEPTION 'Imported artifacts can only be erased';
            END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER guard_skill_import BEFORE UPDATE OR DELETE ON memory_skill_imports
            FOR EACH ROW EXECUTE FUNCTION guard_skill_import();
    """)


def downgrade() -> None:
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM memory_asset_grants) OR EXISTS (SELECT 1 FROM memory_knowledge_documents)
                OR EXISTS (SELECT 1 FROM memory_skill_imports) OR EXISTS (SELECT 1 FROM memory_asset_feedback) THEN
                RAISE EXCEPTION '008 downgrade refused: team asset history exists';
            END IF;
        END $$;
        DROP TABLE memory_asset_feedback, memory_skill_imports, memory_knowledge_events,
                   memory_knowledge_documents, memory_asset_grants;
        DROP FUNCTION guard_team_receipt(), guard_asset_grant(), guard_skill_import();
    """)
