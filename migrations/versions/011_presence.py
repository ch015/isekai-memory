"""M9 opt-in session observations, separate admin policy and anti-replay state."""

from alembic import op

revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE memory_presence_policies (
            project_id text PRIMARY KEY, version integer NOT NULL CHECK(version>0),
            policy jsonb NOT NULL CHECK(jsonb_typeof(policy)='object'),
            updated_by text NOT NULL, updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
        );
        CREATE TABLE memory_presence_sessions (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(), project_id text NOT NULL, actor_id text NOT NULL,
            client_instance_id uuid NOT NULL, session_token_digest text NOT NULL, register_digest text NOT NULL,
            host_kind text NOT NULL CHECK(host_kind IN ('codex','claude','kiro','unknown')),
            session_kind text NOT NULL CHECK(session_kind IN ('worker','controller')),
            parent_session_id uuid,
            classification text NOT NULL CHECK(classification IN ('public','internal','confidential','restricted')),
            sequence integer NOT NULL DEFAULT 0 CHECK(sequence>=0),
            state_sequence integer NOT NULL DEFAULT 0 CHECK(state_sequence>=0),
            report_digest text, reported_policy_version integer NOT NULL DEFAULT 0 CHECK(reported_policy_version>=0),
            reported_state text NOT NULL DEFAULT 'unknown'
                CHECK(reported_state IN ('running','waiting_approval','blocked','idle','unknown')),
            observation_scope text NOT NULL DEFAULT 'partial' CHECK(observation_scope IN ('worker','controller','partial')),
            state_observation_available boolean NOT NULL DEFAULT false,
            active_work_count integer NOT NULL DEFAULT 0 CHECK(active_work_count BETWEEN 0 AND 128),
            work_unit_id uuid, checkpoint_id uuid,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            last_seen_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            state_since_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            idle_since_at timestamptz, ended_at timestamptz, retired_at timestamptz,
            UNIQUE(project_id,actor_id,client_instance_id), UNIQUE(id,project_id),
            FOREIGN KEY(parent_session_id,project_id) REFERENCES memory_presence_sessions(id,project_id) ON DELETE RESTRICT,
            FOREIGN KEY(work_unit_id,project_id) REFERENCES memory_continuity_units(id,project_id) ON DELETE RESTRICT,
            FOREIGN KEY(checkpoint_id,project_id) REFERENCES memory_checkpoints(id,project_id) ON DELETE RESTRICT
        );
        CREATE INDEX idx_presence_project ON memory_presence_sessions(project_id,last_seen_at DESC,id DESC)
            WHERE retired_at IS NULL;
        CREATE INDEX idx_presence_actor ON memory_presence_sessions(project_id,actor_id,created_at DESC,id DESC);
        CREATE FUNCTION guard_presence_session() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Presence anti-replay tombstones cannot be deleted'; END IF;
            IF (to_jsonb(NEW)-ARRAY['host_kind','classification','sequence','state_sequence','report_digest',
                    'reported_policy_version','reported_state','observation_scope','state_observation_available',
                    'active_work_count','work_unit_id','checkpoint_id','last_seen_at','state_since_at',
                    'idle_since_at','ended_at','retired_at']) IS DISTINCT FROM
               (to_jsonb(OLD)-ARRAY['host_kind','classification','sequence','state_sequence','report_digest',
                    'reported_policy_version','reported_state','observation_scope','state_observation_available',
                    'active_work_count','work_unit_id','checkpoint_id','last_seen_at','state_since_at',
                    'idle_since_at','ended_at','retired_at']) THEN
                RAISE EXCEPTION 'Presence identity and registration are immutable';
            END IF;
            IF OLD.retired_at IS NOT NULL OR NEW.sequence<OLD.sequence OR NEW.state_sequence<OLD.state_sequence
               OR (OLD.ended_at IS NOT NULL AND NEW.ended_at IS DISTINCT FROM OLD.ended_at) THEN
                RAISE EXCEPTION 'Presence end/retirement/sequence is irreversible';
            END IF;
            IF OLD.ended_at IS NOT NULL AND NEW.retired_at IS NULL AND NEW IS DISTINCT FROM OLD THEN
                RAISE EXCEPTION 'Ended presence can only be retired';
            END IF;
            IF array_position(ARRAY['public','internal','confidential','restricted'],NEW.classification) <
               array_position(ARRAY['public','internal','confidential','restricted'],OLD.classification) THEN
                RAISE EXCEPTION 'Presence classification cannot decrease';
            END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER guard_presence_session BEFORE UPDATE OR DELETE ON memory_presence_sessions
            FOR EACH ROW EXECUTE FUNCTION guard_presence_session();
    """)


def downgrade():
    op.execute("""
        LOCK TABLE memory_presence_sessions,memory_presence_policies IN ACCESS EXCLUSIVE MODE;
        DO $$ BEGIN
            IF EXISTS(SELECT 1 FROM memory_presence_sessions) OR EXISTS(SELECT 1 FROM memory_presence_policies)
            THEN RAISE EXCEPTION '011 downgrade refused: observation/anti-replay history exists'; END IF;
        END $$;
        DROP TABLE memory_presence_sessions,memory_presence_policies;
        DROP FUNCTION guard_presence_session();
    """)
