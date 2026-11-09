-- Campaigns freeze a gift version and audience. Claims commit with game rewards.
CREATE TABLE IF NOT EXISTS dnf_gm.campaigns (
 id char(32) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
 name varchar(80) NOT NULL,
 status varchar(16) CHARACTER SET ascii NOT NULL,
 revision int unsigned NOT NULL,
 definition_json longtext NOT NULL,
 reward_json longtext NOT NULL,
 binding_json longtext NOT NULL,
 definition_hash char(64) CHARACTER SET ascii NOT NULL,
 activated tinyint unsigned NOT NULL DEFAULT 0,
 created_at bigint NOT NULL,
 updated_at bigint NOT NULL,
 KEY state_updated(status,updated_at,id)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS dnf_gm.campaign_claims (
 campaign_id char(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 subject_id int unsigned NOT NULL,
 target_uid int NOT NULL,
 charac_no int NOT NULL,
 operation_id char(32) CHARACTER SET ascii NOT NULL UNIQUE,
 created_at bigint NOT NULL,
 PRIMARY KEY(campaign_id,subject_id),
 KEY account_claims(campaign_id,target_uid)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS dnf_gm.campaign_links (
 campaign_id char(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 kind varchar(16) CHARACTER SET ascii NOT NULL,
 reference_id char(32) CHARACTER SET ascii NOT NULL,
 created_at bigint NOT NULL,
 PRIMARY KEY(campaign_id,kind,reference_id),
 KEY reference_lookup(kind,reference_id)
) ENGINE=InnoDB;
INSERT IGNORE INTO dnf_gm.schema_versions(version) VALUES(18);
