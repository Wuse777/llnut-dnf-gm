-- Shared locking reads fence every configured ordinary game-write transaction.
-- The root maintenance coordinator waits on the same row FOR UPDATE after
-- freezing application admission. No game schema or data changes.
CREATE TABLE IF NOT EXISTS dnf_gm.gameplay_fence (
 id tinyint unsigned NOT NULL PRIMARY KEY,
 protocol_version int unsigned NOT NULL
) ENGINE=InnoDB;
INSERT IGNORE INTO dnf_gm.gameplay_fence(id,protocol_version) VALUES(1,1);
INSERT IGNORE INTO dnf_gm.schema_versions(version) VALUES(13);
