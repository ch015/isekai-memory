-- Recipient eligibility matches membership and live credentials (PostgreSQL 018).
CREATE VIEW memory_eligible_members AS
SELECT project_id,user_id,min(created_at) AS created_at FROM (
    SELECT t.project_id,t.user_id,t.created_at FROM access_tokens t
        LEFT JOIN memory_projects p ON p.project_id=t.project_id
        LEFT JOIN memory_project_members m ON m.project_id=p.project_id AND m.user_id=t.user_id
        WHERE t.revoked_at IS NULL AND (t.expires_at IS NULL OR t.expires_at>clock_timestamp())
        AND NOT memory_array_contains(t.scopes,'projects')
        AND (memory_array_contains(t.scopes,'admin') OR
             (memory_array_contains(t.scopes,'read') AND memory_array_contains(t.scopes,'write')))
        AND (p.project_id IS NULL OR p.owner_id=t.user_id OR m.role='write')
    UNION ALL
    SELECT p.project_id,t.user_id,t.created_at FROM access_tokens t
        JOIN memory_projects p ON p.owner_id=t.user_id OR EXISTS (
            SELECT 1 FROM memory_project_members m
            WHERE m.project_id=p.project_id AND m.user_id=t.user_id AND m.role='write')
        WHERE t.revoked_at IS NULL AND (t.expires_at IS NULL OR t.expires_at>clock_timestamp())
        AND memory_array_contains(t.scopes,'projects')
        AND (memory_array_contains(t.scopes,'admin') OR
             (memory_array_contains(t.scopes,'read') AND memory_array_contains(t.scopes,'write')))
    UNION ALL
    SELECT p.project_id,i.user_id,i.created_at FROM memory_identities i
        JOIN memory_projects p ON p.organization_id=i.organization_id
        LEFT JOIN memory_project_members m ON m.project_id=p.project_id AND m.user_id=i.user_id
        WHERE i.disabled_at IS NULL AND (p.owner_id=i.user_id OR m.role='write')
    UNION ALL
    SELECT p.project_id,i.user_id,i.created_at FROM memory_github_identities i
        JOIN memory_projects p ON p.organization_id=i.organization_id
        LEFT JOIN memory_project_members m ON m.project_id=p.project_id AND m.user_id=i.user_id
        WHERE i.disabled_at IS NULL AND (p.owner_id=i.user_id OR m.role='write')
) members GROUP BY project_id,user_id;
