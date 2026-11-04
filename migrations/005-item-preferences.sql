-- Single-administrator convenience metadata. No game writes or copied PVF content.
CREATE TABLE IF NOT EXISTS dnf_gm.item_preferences (
 pvf_sha256 char(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 item_id int unsigned NOT NULL,
 favorite tinyint unsigned NOT NULL DEFAULT 0,
 favorited_at datetime(6) DEFAULT NULL,
 selected_at datetime(6) DEFAULT NULL,
 PRIMARY KEY(pvf_sha256,item_id),
 KEY favorites(pvf_sha256,favorite,favorited_at,item_id),
 KEY recents(pvf_sha256,selected_at,item_id)
) ENGINE=InnoDB;
INSERT IGNORE INTO dnf_gm.schema_versions(version) VALUES(5);
