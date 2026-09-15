"""Durable generation receipts and reference-only summary snapshots.

Revision ID: 006
Revises: 005
"""

from alembic import op

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE memory_generation_jobs (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            project_id text NOT NULL,
            kind text NOT NULL CHECK (kind IN ('extract','summary')),
            source_key text NOT NULL,
            source_watermark text NOT NULL,
            recipe text NOT NULL,
            provider text NOT NULL,
            model_version text NOT NULL,
            prompt_version text NOT NULL,
            parameters jsonb NOT NULL,
            enqueued_by text NOT NULL,
            status text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','running','succeeded','dead')),
            version integer NOT NULL DEFAULT 1 CHECK (version > 0),
            attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
            max_attempts integer NOT NULL DEFAULT 3 CHECK (max_attempts BETWEEN 1 AND 30),
            lease_token uuid,
            lease_until timestamptz,
            available_at timestamptz NOT NULL DEFAULT now(),
            error_code text,
            outcome jsonb,
            redrive_version integer,
            redrive_actor text,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (project_id,kind,source_key,source_watermark,recipe),
            UNIQUE (id,project_id),
            CHECK ((status='running') = (lease_token IS NOT NULL AND lease_until IS NOT NULL))
        );
        CREATE INDEX idx_generation_ready ON memory_generation_jobs(project_id,status,available_at,created_at,id);
        CREATE TABLE memory_generation_attempts (
            job_id uuid NOT NULL REFERENCES memory_generation_jobs(id) ON DELETE RESTRICT,
            attempt integer NOT NULL,
            started_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            finished_at timestamptz,
            outcome_code text,
            input_chars integer NOT NULL DEFAULT 0,
            output_chars integer NOT NULL DEFAULT 0,
            cost_microusd bigint NOT NULL DEFAULT 0 CHECK (cost_microusd = 0),
            PRIMARY KEY (job_id,attempt)
        );
        CREATE TABLE memory_summary_snapshots (
            job_id uuid PRIMARY KEY,
            project_id text NOT NULL,
            source_watermark text NOT NULL,
            scope jsonb NOT NULL,
            source_count integer NOT NULL,
            dependencies jsonb NOT NULL,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            FOREIGN KEY (job_id,project_id) REFERENCES memory_generation_jobs(id,project_id) ON DELETE RESTRICT
        );
        CREATE INDEX idx_summary_scope ON memory_summary_snapshots(project_id,created_at DESC,job_id);
    """)


def downgrade() -> None:
    # Do not silently lose source coverage, leases, dead letters or attribution.
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM memory_generation_jobs) THEN
                RAISE EXCEPTION '006 downgrade refused: generation receipts exist; retain or explicitly export them first';
            END IF;
        END $$;
        DROP TABLE memory_summary_snapshots;
        DROP TABLE memory_generation_attempts;
        DROP TABLE memory_generation_jobs;
    """)
