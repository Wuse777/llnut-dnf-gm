-- Management-only schedules and durable backup identities. No game-table writes.
CREATE TABLE IF NOT EXISTS dnf_gm.backup_schedule (
 id tinyint unsigned NOT NULL PRIMARY KEY,
 revision int unsigned NOT NULL DEFAULT 1,
 enabled tinyint unsigned NOT NULL DEFAULT 1,
 hour tinyint unsigned NOT NULL DEFAULT 4,
 minute tinyint unsigned NOT NULL DEFAULT 0,
 retention_days tinyint unsigned NOT NULL DEFAULT 7,
 failure_alerts tinyint unsigned NOT NULL DEFAULT 1,
 updated_at double NOT NULL
) ENGINE=InnoDB;
INSERT IGNORE INTO dnf_gm.backup_schedule(id,updated_at) VALUES(1,UNIX_TIMESTAMP());
CREATE TABLE IF NOT EXISTS dnf_gm.backup_runs (
 run_id char(32) NOT NULL PRIMARY KEY,
 run_key varchar(64) NOT NULL,
 origin varchar(16) NOT NULL,
 state varchar(24) NOT NULL,
 reason varchar(200) NOT NULL,
 spec_json mediumtext NOT NULL,
 result_json mediumtext,
 error_code varchar(48),
 created_at double NOT NULL,
 started_at double,
 finished_at double,
 UNIQUE KEY run_key(run_key),
 KEY pending(state,created_at),
 KEY recent(created_at,run_id)
) ENGINE=InnoDB;
INSERT IGNORE INTO dnf_gm.schema_versions(version) VALUES(16);
