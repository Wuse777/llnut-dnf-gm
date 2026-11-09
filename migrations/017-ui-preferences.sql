-- Single administrator UI metadata. It contains no rewards or game operations.
CREATE TABLE IF NOT EXISTS dnf_gm.ui_preference_state (
 id tinyint unsigned NOT NULL PRIMARY KEY,
 revision bigint unsigned NOT NULL DEFAULT 0
) ENGINE=InnoDB;
INSERT IGNORE INTO dnf_gm.ui_preference_state(id,revision) VALUES(1,0);
CREATE TABLE IF NOT EXISTS dnf_gm.ui_preferences (
 pvf_sha256 char(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 kind varchar(24) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 name varchar(48) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
 version int unsigned NOT NULL,
 payload_json json DEFAULT NULL,
 deleted tinyint unsigned NOT NULL DEFAULT 0,
 updated_at datetime(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 PRIMARY KEY(pvf_sha256,kind,name),
 KEY active_preferences(pvf_sha256,kind,deleted,updated_at)
) ENGINE=InnoDB;
INSERT IGNORE INTO dnf_gm.schema_versions(version) VALUES(17);
