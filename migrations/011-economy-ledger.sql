-- Derived, immutable GM reward reporting ledger, never player economy tables.
CREATE TABLE IF NOT EXISTS dnf_gm.economy_operations (
 operation_id char(32) CHARACTER SET ascii PRIMARY KEY,
 projection_id bigint unsigned NOT NULL AUTO_INCREMENT UNIQUE,
 audit_id bigint unsigned NOT NULL UNIQUE,
 target_uid int NOT NULL,
 charac_no int NULL,
 action varchar(16) CHARACTER SET ascii NOT NULL,
 source varchar(16) CHARACTER SET ascii NOT NULL,
 actor varchar(64) NOT NULL,
 reason varchar(200) NOT NULL,
 template_id bigint unsigned NULL,
 template_version int NULL,
 source_hash char(64) CHARACTER SET ascii NOT NULL,
 complete tinyint NOT NULL,
 issue varchar(120) NOT NULL DEFAULT '',
 created_at datetime NOT NULL,
 KEY time_window(created_at,audit_id),
 KEY target_window(target_uid,created_at,audit_id)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS dnf_gm.economy_values (
 operation_id char(32) CHARACTER SET ascii NOT NULL,
 metric varchar(16) CHARACTER SET ascii NOT NULL,
 item_id int unsigned NOT NULL DEFAULT 0,
 pvf_sha256 char(64) CHARACTER SET ascii NOT NULL DEFAULT '',
 item_name varchar(255) NOT NULL DEFAULT '',
 amount bigint NOT NULL,
 PRIMARY KEY(operation_id,metric,item_id,pvf_sha256)
) ENGINE=InnoDB;
INSERT IGNORE INTO dnf_gm.schema_versions(version) VALUES(11);
