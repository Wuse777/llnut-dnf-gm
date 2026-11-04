CREATE TABLE IF NOT EXISTS dnf_gm.player_profiles (
 uid int PRIMARY KEY,
 revision int unsigned NOT NULL,
 notes text NOT NULL,
 tags_json text NOT NULL,
 updated_at bigint NOT NULL
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS dnf_gm.support_cases (
 case_id char(32) CHARACTER SET ascii PRIMARY KEY,
 uid int NOT NULL,
 charac_no int NULL,
 target_json text NOT NULL,
 title varchar(120) NOT NULL,
 category varchar(24) CHARACTER SET ascii NOT NULL,
 description text NOT NULL,
 status varchar(16) CHARACTER SET ascii NOT NULL,
 revision int unsigned NOT NULL,
 compensation_count int unsigned NOT NULL DEFAULT 0,
 created_at bigint NOT NULL,
 updated_at bigint NOT NULL,
 KEY account_cases(uid,updated_at,case_id),
 KEY status_cases(status,updated_at,case_id),
 KEY recent_cases(updated_at,case_id)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS dnf_gm.support_events (
 case_id char(32) CHARACTER SET ascii NOT NULL,
 revision int unsigned NOT NULL,
 kind varchar(24) CHARACTER SET ascii NOT NULL,
 note text NOT NULL,
 details_json text NOT NULL,
 created_at bigint NOT NULL,
 PRIMARY KEY(case_id,revision)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS dnf_gm.support_links (
 case_id char(32) CHARACTER SET ascii NOT NULL,
 operation_id char(32) CHARACTER SET ascii NOT NULL,
 relation varchar(16) CHARACTER SET ascii NOT NULL,
 created_at bigint NOT NULL,
 PRIMARY KEY(case_id,operation_id)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS dnf_gm.support_requests (
 request_key varchar(64) CHARACTER SET ascii PRIMARY KEY,
 fingerprint char(64) CHARACTER SET ascii NOT NULL,
 result_json text NOT NULL,
 created_at bigint NOT NULL
) ENGINE=InnoDB;
INSERT IGNORE INTO dnf_gm.schema_versions(version) VALUES(10);
