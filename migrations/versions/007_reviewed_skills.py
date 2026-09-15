"""Immutable reviewed Skill revisions, source erasure and durable generation.

Revision ID: 007
Revises: 006
"""

from alembic import op

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE memory_generation_jobs DROP CONSTRAINT memory_generation_jobs_kind_check;
        ALTER TABLE memory_generation_jobs ADD CONSTRAINT memory_generation_jobs_kind_check
            CHECK (kind IN ('extract','summary','skill'));
        CREATE TABLE memory_skills (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            project_id text NOT NULL,
            name text NOT NULL,
            latest_revision integer NOT NULL DEFAULT 0,
            active_revision integer,
            classification text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            UNIQUE (id,project_id), UNIQUE (project_id,name)
        );
        CREATE TABLE memory_skill_revisions (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            skill_id uuid NOT NULL,
            project_id text NOT NULL,
            revision integer NOT NULL CHECK (revision > 0),
            base_active_revision integer,
            version integer NOT NULL DEFAULT 1 CHECK (version > 0),
            status text NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending','active','rejected','archived','superseded','stale','forgotten')),
            origin text NOT NULL CHECK (origin IN ('manual','generated')),
            body jsonb NOT NULL,
            classification text NOT NULL CHECK (classification IN ('public','internal','confidential','restricted')),
            source_lock_digest text NOT NULL,
            source_watermark text NOT NULL,
            content_digest text NOT NULL,
            created_by text NOT NULL,
            idempotency_key text NOT NULL,
            submission_digest text NOT NULL,
            approved_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            UNIQUE (id,project_id), UNIQUE (skill_id,revision),
            UNIQUE (project_id,created_by,idempotency_key),
            FOREIGN KEY (skill_id,project_id) REFERENCES memory_skills(id,project_id) ON DELETE RESTRICT,
            CHECK ((status='forgotten') = (body='{}'::jsonb)),
            CHECK (status!='active' OR (origin='manual' AND approved_at IS NOT NULL))
        );
        CREATE UNIQUE INDEX idx_skill_active ON memory_skill_revisions(skill_id) WHERE status='active';
        CREATE INDEX idx_skill_review ON memory_skill_revisions(project_id,status,created_at DESC,id DESC);
        CREATE TABLE memory_skill_sources (
            revision_id uuid NOT NULL,
            project_id text NOT NULL,
            memory_id uuid NOT NULL,
            memory_version integer NOT NULL,
            binding jsonb NOT NULL,
            PRIMARY KEY (revision_id,memory_id),
            FOREIGN KEY (revision_id,project_id) REFERENCES memory_skill_revisions(id,project_id) ON DELETE RESTRICT,
            FOREIGN KEY (memory_id,project_id) REFERENCES memory_experiences(id,project_id) ON DELETE RESTRICT
        );
        CREATE INDEX idx_skill_source_memory ON memory_skill_sources(memory_id);
        CREATE FUNCTION guard_skill_source() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'Skill source bindings are immutable'; END $$;
        CREATE TRIGGER guard_skill_source BEFORE UPDATE OR DELETE ON memory_skill_sources
            FOR EACH ROW EXECUTE FUNCTION guard_skill_source();
        CREATE TABLE memory_skill_events (
            revision_id uuid NOT NULL REFERENCES memory_skill_revisions(id) ON DELETE RESTRICT,
            version integer NOT NULL,
            actor_id text NOT NULL,
            action text NOT NULL,
            previous_status text NOT NULL,
            applied_status text NOT NULL,
            cause_memory_id uuid,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            PRIMARY KEY (revision_id,version)
        );
        CREATE FUNCTION guard_skill_revision() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF (to_jsonb(NEW) - ARRAY['status','version','body','approved_at','updated_at']) IS DISTINCT FROM
               (to_jsonb(OLD) - ARRAY['status','version','body','approved_at','updated_at']) OR
               (NEW.body IS DISTINCT FROM OLD.body AND NOT (NEW.status='forgotten' AND NEW.body='{}'::jsonb)) OR
               (OLD.status='forgotten' AND NEW.status!='forgotten') OR
               (OLD.approved_at IS NOT NULL AND NEW.approved_at IS DISTINCT FROM OLD.approved_at) THEN
                RAISE EXCEPTION 'Skill content and attribution are immutable';
            END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER guard_skill_revision BEFORE UPDATE ON memory_skill_revisions
            FOR EACH ROW EXECUTE FUNCTION guard_skill_revision();
        CREATE FUNCTION invalidate_source_skills() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE target record; next_status text;
        BEGIN
            IF NEW.status=OLD.status AND NEW.version=OLD.version THEN RETURN NEW; END IF;
            FOR target IN
                SELECT r.* FROM memory_skill_revisions r JOIN memory_skill_sources s ON s.revision_id=r.id
                WHERE s.memory_id=NEW.id AND r.status!='forgotten'
                  AND (NEW.status='forgotten' OR (r.status IN ('pending','active')
                       AND (NEW.status!='active' OR NEW.version!=s.memory_version)))
                ORDER BY r.id FOR UPDATE OF r
            LOOP
                next_status := CASE WHEN NEW.status='forgotten' THEN 'forgotten' ELSE 'stale' END;
                UPDATE memory_skill_revisions SET status=next_status, version=version+1,
                    body=CASE WHEN next_status='forgotten' THEN '{}'::jsonb ELSE body END,
                    updated_at=clock_timestamp() WHERE id=target.id;
                UPDATE memory_skills SET active_revision=NULL
                    WHERE id=target.skill_id AND active_revision=target.revision;
                INSERT INTO memory_skill_events
                    (revision_id,version,actor_id,action,previous_status,applied_status,cause_memory_id)
                VALUES (target.id,target.version+1,'source-lifecycle','invalidate',target.status,next_status,NEW.id);
            END LOOP;
            RETURN NEW;
        END $$;
        CREATE TRIGGER invalidate_source_skills AFTER UPDATE ON memory_experiences
            FOR EACH ROW EXECUTE FUNCTION invalidate_source_skills();
    """)


def downgrade() -> None:
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM memory_skill_revisions) OR
               EXISTS (SELECT 1 FROM memory_generation_jobs WHERE kind='skill') THEN
                RAISE EXCEPTION '007 downgrade refused: Skill history or generation receipts exist';
            END IF;
        END $$;
        DROP TRIGGER invalidate_source_skills ON memory_experiences;
        DROP FUNCTION invalidate_source_skills();
        DROP TABLE memory_skill_events;
        DROP TABLE memory_skill_sources;
        DROP FUNCTION guard_skill_source();
        DROP TABLE memory_skill_revisions;
        DROP FUNCTION guard_skill_revision();
        DROP TABLE memory_skills;
        ALTER TABLE memory_generation_jobs DROP CONSTRAINT memory_generation_jobs_kind_check;
        ALTER TABLE memory_generation_jobs ADD CONSTRAINT memory_generation_jobs_kind_check CHECK (kind IN ('extract','summary'));
    """)
