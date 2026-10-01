-- Source erasure/retirement invalidates dependent Skills in the same transaction.
CREATE TRIGGER invalidate_source_skills AFTER UPDATE ON memory_experiences
WHEN NEW.status IS NOT OLD.status OR NEW.version IS NOT OLD.version
BEGIN
    INSERT INTO memory_skill_events
        (revision_id,version,actor_id,action,previous_status,applied_status,cause_memory_id)
    SELECT r.id,r.version+1,'source-lifecycle','invalidate',r.status,
           CASE WHEN NEW.status='forgotten' THEN 'forgotten' ELSE 'stale' END,NEW.id
    FROM memory_skill_revisions r JOIN memory_skill_sources s ON s.revision_id=r.id
    WHERE s.memory_id=NEW.id AND r.status!='forgotten'
      AND (NEW.status='forgotten' OR (r.status IN ('pending','active')
           AND (NEW.status!='active' OR NEW.version!=s.memory_version)));

    UPDATE memory_skills SET active_revision=NULL
    WHERE EXISTS (
        SELECT 1 FROM memory_skill_revisions r JOIN memory_skill_sources s ON s.revision_id=r.id
        WHERE r.skill_id=memory_skills.id AND r.revision=memory_skills.active_revision
          AND s.memory_id=NEW.id AND r.status!='forgotten'
          AND (NEW.status='forgotten' OR (r.status IN ('pending','active')
               AND (NEW.status!='active' OR NEW.version!=s.memory_version)))
    );

    UPDATE memory_skill_revisions
    SET status=CASE WHEN NEW.status='forgotten' THEN 'forgotten' ELSE 'stale' END,
        version=version+1,
        body=CASE WHEN NEW.status='forgotten' THEN '{}' ELSE body END,
        updated_at=clock_timestamp()
    WHERE id IN (
        SELECT r.id FROM memory_skill_revisions r JOIN memory_skill_sources s ON s.revision_id=r.id
        WHERE s.memory_id=NEW.id AND r.status!='forgotten'
          AND (NEW.status='forgotten' OR (r.status IN ('pending','active')
               AND (NEW.status!='active' OR NEW.version!=s.memory_version)))
    );
END;
