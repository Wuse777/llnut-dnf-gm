CREATE TABLE IF NOT EXISTS dnf_gm.capability_policy (
 id tinyint unsigned PRIMARY KEY,
 revision bigint unsigned NOT NULL,
 enabled_json text NOT NULL,
 updated_at bigint NOT NULL
) ENGINE=InnoDB;
INSERT IGNORE INTO dnf_gm.capability_policy VALUES(1,0,'[]',0);
CREATE TABLE IF NOT EXISTS dnf_gm.capability_requests (
 request_id char(32) CHARACTER SET ascii PRIMARY KEY,
 fingerprint char(64) CHARACTER SET ascii NOT NULL,
 result_json text NOT NULL,
 created_at bigint NOT NULL
) ENGINE=InnoDB;
INSERT IGNORE INTO dnf_gm.schema_versions(version) VALUES(12);
