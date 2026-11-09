-- Explicit game restore points. No automatic game-stop or production restore.
CREATE TABLE IF NOT EXISTS dnf_gm.game_backup_control (
 id tinyint unsigned NOT NULL PRIMARY KEY,
 revision bigint unsigned NOT NULL DEFAULT 1
) ENGINE=InnoDB;
INSERT IGNORE INTO dnf_gm.game_backup_control(id,revision) VALUES(1,1);
CREATE TABLE IF NOT EXISTS dnf_gm.game_backup_runs (
 run_id char(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL PRIMARY KEY,
 backup_id char(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 action varchar(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 window_id char(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 reason varchar(200) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
 state varchar(24) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 fingerprint char(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 spec_json json NOT NULL,
 result_json json DEFAULT NULL,
 created_at double NOT NULL,
 expires_at double NOT NULL,
 started_at double DEFAULT NULL,
 finished_at double DEFAULT NULL,
 error_code varchar(96) CHARACTER SET ascii COLLATE ascii_bin DEFAULT NULL,
 KEY pending_runs(state,created_at),
 KEY backup_actions(backup_id,action,created_at)
) ENGINE=InnoDB;
INSERT IGNORE INTO dnf_gm.schema_versions(version) VALUES(19);
