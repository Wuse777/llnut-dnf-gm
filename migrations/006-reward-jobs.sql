-- Frozen target sets and per-target durable execution state, management schema only.
CREATE TABLE IF NOT EXISTS dnf_gm.reward_jobs (
 id char(32) CHARACTER SET ascii PRIMARY KEY,
 session_hash char(64) CHARACTER SET ascii NOT NULL,
 idempotency_key varchar(64) CHARACTER SET ascii COLLATE ascii_bin NULL UNIQUE,
 fingerprint char(64) CHARACTER SET ascii NOT NULL,
 request_json longtext NOT NULL,
 preview_json longtext NOT NULL,
 status varchar(24) NOT NULL,
 reason varchar(200) NOT NULL,
 pause_reason varchar(200) NOT NULL DEFAULT '',
 target_count int unsigned NOT NULL DEFAULT 0,
 account_count int unsigned NOT NULL DEFAULT 0,
 created_at bigint NOT NULL,
 expires_at bigint NOT NULL,
 confirmed_at bigint DEFAULT NULL,
 KEY pending(status,created_at,id)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS dnf_gm.reward_targets (
 job_id char(32) CHARACTER SET ascii NOT NULL,
 ordinal int unsigned NOT NULL,
 target_uid int NOT NULL,
 charac_no int NOT NULL,
 target_json text NOT NULL,
 operation_id char(32) CHARACTER SET ascii NOT NULL UNIQUE,
 status varchar(24) NOT NULL DEFAULT 'pending',
 attempts int unsigned NOT NULL DEFAULT 0,
 error_type varchar(64) NOT NULL DEFAULT '',
 error_message varchar(200) NOT NULL DEFAULT '',
 last_attempt bigint DEFAULT NULL,
 PRIMARY KEY(job_id,ordinal), UNIQUE KEY recipient(job_id,charac_no),
 KEY work(job_id,status,ordinal), KEY recovery(status,job_id,ordinal), KEY account(job_id,target_uid)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS dnf_gm.reward_account_credits (
 job_id char(32) CHARACTER SET ascii NOT NULL,
 target_uid int NOT NULL,
 operation_id char(32) CHARACTER SET ascii NOT NULL,
 PRIMARY KEY(job_id,target_uid)
) ENGINE=InnoDB;
INSERT IGNORE INTO dnf_gm.schema_versions(version) VALUES(6);
