-- Bounded newest-first workbench reads; preserves the maintenance outcome index.
SET @workbench_index_sql = (SELECT IF(COUNT(*)>0,'SELECT 1','ALTER TABLE dnf_gm.operations ADD KEY workbench_created(status,created_at,operation_id)') FROM information_schema.STATISTICS WHERE TABLE_SCHEMA='dnf_gm' AND TABLE_NAME='operations' AND INDEX_NAME='workbench_created');
PREPARE workbench_index_stmt FROM @workbench_index_sql;
EXECUTE workbench_index_stmt;
DEALLOCATE PREPARE workbench_index_stmt;
SET @mail_item_index_sql = (SELECT IF(COUNT(*)>0,'SELECT 1','ALTER TABLE dnf_gm.mail_deliveries ADD KEY operation_item(operation_id,item_id)') FROM information_schema.STATISTICS WHERE TABLE_SCHEMA='dnf_gm' AND TABLE_NAME='mail_deliveries' AND INDEX_NAME='operation_item');
PREPARE mail_item_index_stmt FROM @mail_item_index_sql;
EXECUTE mail_item_index_stmt;
DEALLOCATE PREPARE mail_item_index_stmt;
INSERT IGNORE INTO dnf_gm.schema_versions(version) VALUES(20);
