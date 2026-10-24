-- Management-only, idempotent and forward-compatible. Never changes game tables.
CREATE TABLE IF NOT EXISTS dnf_gm.catalog_policy_state (id tinyint PRIMARY KEY, revision bigint unsigned NOT NULL) ENGINE=InnoDB;
INSERT IGNORE INTO dnf_gm.catalog_policy_state VALUES(1,0);
CREATE TABLE IF NOT EXISTS dnf_gm.catalog_policy_items (pvf_sha256 char(64) CHARACTER SET ascii NOT NULL,item_id int unsigned NOT NULL,enabled tinyint NOT NULL,reason varchar(200) NOT NULL,revision bigint unsigned NOT NULL,verification_evidence varchar(500) NOT NULL DEFAULT '',PRIMARY KEY(pvf_sha256,item_id)) ENGINE=InnoDB;
INSERT IGNORE INTO dnf_gm.schema_versions(version) VALUES(2);
