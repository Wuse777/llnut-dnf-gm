-- Bounded maintenance outcome lookup, management schema only. Retry-safe.
SET @outcome_index_sql = (SELECT IF(COUNT(*)>0,'SELECT 1','ALTER TABLE dnf_gm.operations ADD KEY outcome_status(status,action,operation_id)') FROM information_schema.STATISTICS WHERE TABLE_SCHEMA='dnf_gm' AND TABLE_NAME='operations' AND INDEX_NAME='outcome_status');
PREPARE outcome_index_stmt FROM @outcome_index_sql;
EXECUTE outcome_index_stmt;
DEALLOCATE PREPARE outcome_index_stmt;
INSERT IGNORE INTO dnf_gm.schema_versions(version) VALUES(14);
