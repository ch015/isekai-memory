# Non-Git work projects — schema 017

2026-09-17. ADE S1/J1/J3: a project is a persistent work identity; Git is optional.
`memory_project_register` accepts omitted or null `git_url` and `git_ref`. Supply both valid strings for a Git resource,
or neither for a work project. Empty strings and partial pairs are invalid. list/get return both fields as null
for a non-Git project. Ownership, membership, token scope, setup digest and revision guards are unchanged.

## Migration and recovery

Deploy server code with `alembic upgrade head` to 017 before enabling ADE automatic non-Git registration.
017 only relaxes the two columns and adds a paired-null constraint. It does not rewrite IDs, setup manifests,
revisions, owners, members, token records, handoffs or experiences. Old Git clients continue to register Git projects.
Older ADE clients cannot acquire non-Git projects; update ADE with the server.

A downgrade to 016 refuses while any non-Git row exists, inside the migration transaction. It never deletes projects
or invents Git URLs to satisfy the old schema. Keep normal operational backups before deployment. This change was
migrated only in a disposable database; the existing local/production service was not changed.

## Verification

- `MEMORY_TEST_DATABASE_URL=<disposable DB> .venv/bin/python -m pytest -q --disable-warnings`: **722 passed**.
- `tests/test_optional_git_migration.py`: actual 016→017 migration, byte-equivalent selected legacy rows/members,
  same IDs/setup/revision, successful non-Git insert, rejected downgrade with rows and revision preserved.
- `tests/test_project_directory_postgres.py`: actual MCP dispatcher with PostgreSQL, no-Git register/list/get,
  idempotent repeat and owner/member assignment, existing permissions and namespace protections.
- ADE `tests/e2e/non-git-projects.spec.ts`: actual TLS Memory/PostgreSQL, Electron/Rust/CORE, outage/retry,
  same ID and different actor opening without Git, real shell PTY. Login provider fixture is tested separately in ADE.

0:N resource management, external document result references, historical record upload and package distribution are
not added by this migration. Existing user changes to compose.yaml/docs/local-docker.md are separate and excluded.
