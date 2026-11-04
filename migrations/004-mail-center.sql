-- Immutable GM delivery ledger. No changes to game schema.
CREATE TABLE IF NOT EXISTS dnf_gm.mail_batches (
 operation_id char(32) CHARACTER SET ascii PRIMARY KEY,
 target_uid int NOT NULL,
 charac_no int NOT NULL,
 account_name varchar(64) NOT NULL,
 character_name varchar(128) NOT NULL,
 letter_id int NOT NULL,
 postal_count bigint unsigned NOT NULL,
 recorded_count bigint unsigned NOT NULL,
 history_complete tinyint NOT NULL DEFAULT 1,
 message varchar(255) NOT NULL,
 request_json longtext NOT NULL,
 created_at timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
 KEY target(target_uid,created_at), KEY recipient(charac_no,created_at), KEY created(created_at)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS dnf_gm.mail_deliveries (
 operation_id char(32) CHARACTER SET ascii NOT NULL,
 ordinal bigint unsigned NOT NULL,
 postal_id int unsigned NOT NULL,
 item_id int unsigned NOT NULL,
 quantity int unsigned NOT NULL,
 gold int unsigned NOT NULL,
 PRIMARY KEY(operation_id,ordinal), UNIQUE KEY postal(postal_id)
) ENGINE=InnoDB;
-- Failure lookup stays indexed as attempts accumulate. Management schema only.
SET @failure_index_sql = (SELECT IF(COUNT(*)>0,'SELECT 1','ALTER TABLE dnf_gm.failures ADD KEY operation_lookup(operation_id,id)') FROM information_schema.STATISTICS WHERE TABLE_SCHEMA='dnf_gm' AND TABLE_NAME='failures' AND INDEX_NAME='operation_lookup');
PREPARE failure_index_stmt FROM @failure_index_sql;
EXECUTE failure_index_stmt;
DEALLOCATE PREPARE failure_index_stmt;
INSERT IGNORE INTO dnf_gm.schema_versions(version) VALUES(4);
