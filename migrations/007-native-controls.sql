CREATE TABLE IF NOT EXISTS dnf_gm.native_controls (
 operation_id char(32) CHARACTER SET ascii PRIMARY KEY,
 target_uid int NULL,
 created_at bigint NOT NULL,
 KEY created(created_at,operation_id),
 KEY target_created(target_uid,created_at,operation_id)
) ENGINE=InnoDB;
INSERT IGNORE INTO dnf_gm.native_controls(operation_id,target_uid,created_at)
 SELECT operation_id,CASE WHEN action='native-notice' THEN NULL ELSE CAST(JSON_UNQUOTE(JSON_EXTRACT(request_json,'$.uid')) AS SIGNED) END,created_at
 FROM dnf_gm.operations WHERE action IN ('native-notice','native-kick','native-ban-kick');
INSERT IGNORE INTO dnf_gm.schema_versions(version) VALUES(7);
