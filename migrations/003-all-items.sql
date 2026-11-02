-- One-time opening of existing item policies. Later manual disables survive
-- repeated upgrades. Never marks an item as client-verified.
START TRANSACTION;
SELECT revision FROM dnf_gm.catalog_policy_state WHERE id=1 FOR UPDATE;
UPDATE dnf_gm.catalog_policy_state SET revision=revision+1 WHERE id=1 AND NOT EXISTS (SELECT 1 FROM dnf_gm.schema_versions WHERE version=3) AND EXISTS (SELECT 1 FROM dnf_gm.catalog_policy_items WHERE enabled=0);
UPDATE dnf_gm.catalog_policy_items SET enabled=1,reason='索引全量开放；客户端未验证',verification_evidence='',revision=revision+1 WHERE enabled=0 AND NOT EXISTS (SELECT 1 FROM dnf_gm.schema_versions WHERE version=3);
INSERT IGNORE INTO dnf_gm.schema_versions(version) VALUES(3);
COMMIT;
