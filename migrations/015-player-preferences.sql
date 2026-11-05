-- Single administrator navigation metadata, never a game operation or a saved reward.
CREATE TABLE IF NOT EXISTS dnf_gm.player_preferences (
 uid int unsigned NOT NULL,
 charac_no int unsigned NOT NULL DEFAULT 0,
 favorite tinyint unsigned NOT NULL DEFAULT 0,
 favorited_at datetime(6) DEFAULT NULL,
 visited_at datetime(6) DEFAULT NULL,
 PRIMARY KEY(uid,charac_no),
 KEY favorites(favorite,favorited_at,uid,charac_no),
 KEY recent(visited_at,uid,charac_no)
) ENGINE=InnoDB;
INSERT IGNORE INTO dnf_gm.schema_versions(version) VALUES(15);
