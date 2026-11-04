CREATE TABLE IF NOT EXISTS dnf_gm.inventory_operations (
 operation_id char(32) CHARACTER SET ascii PRIMARY KEY,
 uid int NOT NULL,
 charac_no int NOT NULL,
 container varchar(32) CHARACTER SET ascii NOT NULL,
 slot smallint unsigned NOT NULL,
 created_at bigint NOT NULL,
 maintenance_id char(32) CHARACTER SET ascii NOT NULL,
 KEY maintenance_operations(maintenance_id,operation_id),
 KEY target_created(uid,created_at,operation_id),
 KEY character_created(charac_no,created_at,operation_id)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS dnf_gm.inventory_snapshots (
 operation_id char(32) CHARACTER SET ascii PRIMARY KEY,
 uid int NOT NULL,
 charac_no int NOT NULL,
 container varchar(32) CHARACTER SET ascii NOT NULL,
 slot smallint unsigned NOT NULL,
 source_operation_id char(32) CHARACTER SET ascii NULL,
 before_blob blob NOT NULL,
 after_blob blob NOT NULL,
 before_sha256 char(64) CHARACTER SET ascii NOT NULL,
 after_sha256 char(64) CHARACTER SET ascii NOT NULL,
 image_digest varchar(80) CHARACTER SET ascii NOT NULL,
 pvf_sha256 char(64) CHARACTER SET ascii NOT NULL,
 program_sha256 char(64) CHARACTER SET ascii NOT NULL,
 maintenance_id char(32) CHARACTER SET ascii NOT NULL,
 created_at timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
 KEY target_created(uid,created_at,operation_id)
) ENGINE=InnoDB;
INSERT IGNORE INTO dnf_gm.schema_versions(version) VALUES(9);
