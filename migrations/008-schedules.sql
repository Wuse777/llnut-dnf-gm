CREATE TABLE IF NOT EXISTS dnf_gm.schedules (
 id char(32) CHARACTER SET ascii PRIMARY KEY,
 session_hash char(64) CHARACTER SET ascii NOT NULL,
 idempotency_key varchar(80) CHARACTER SET ascii NULL UNIQUE,
 fingerprint char(64) CHARACTER SET ascii NOT NULL,
 title varchar(100) NOT NULL,
 kind varchar(16) CHARACTER SET ascii NOT NULL,
 request_json mediumtext NOT NULL,
 preview_json mediumtext NOT NULL,
 status varchar(24) CHARACTER SET ascii NOT NULL,
 next_due bigint NULL,
 created_at bigint NOT NULL,
 expires_at bigint NOT NULL,
 activated_at bigint NULL,
 last_error varchar(200) NOT NULL DEFAULT '',
 KEY due(status,next_due,id),
 KEY created(created_at,id)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS dnf_gm.schedule_runs (
 id char(32) CHARACTER SET ascii PRIMARY KEY,
 schedule_id char(32) CHARACTER SET ascii NOT NULL,
 due_at bigint NOT NULL,
 started_at bigint NOT NULL,
 finished_at bigint NULL,
 checked_at bigint NOT NULL,
 status varchar(24) CHARACTER SET ascii NOT NULL,
 reference_kind varchar(16) CHARACTER SET ascii NULL,
 reference_id char(32) CHARACTER SET ascii NULL,
 skipped_count bigint NOT NULL DEFAULT 0,
 last_due_at bigint NULL,
 error_message varchar(200) NOT NULL DEFAULT '',
 UNIQUE KEY occurrence(schedule_id,due_at),
 KEY history(schedule_id,due_at,id),
 KEY recovery(status,checked_at,id)
) ENGINE=InnoDB;
INSERT IGNORE INTO dnf_gm.schema_versions(version) VALUES(8);
