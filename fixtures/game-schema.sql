-- Metadata-only snapshot from fixed QF1031 / MySQL 5.7.44; no player rows.

CREATE DATABASE IF NOT EXISTS taiwan_cain;

USE taiwan_cain;

CREATE TABLE `charac_info` (
  `m_id` int(11) NOT NULL DEFAULT '0',
  `charac_no` int(11) NOT NULL AUTO_INCREMENT,
  `charac_name` varchar(20) NOT NULL DEFAULT '',
  `village` tinyint(4) NOT NULL DEFAULT '1',
  `job` tinyint(4) NOT NULL DEFAULT '0',
  `lev` tinyint(4) NOT NULL DEFAULT '1',
  `exp` int(11) NOT NULL DEFAULT '0',
  `grow_type` tinyint(4) NOT NULL DEFAULT '0',
  `HP` tinyint(3) unsigned NOT NULL DEFAULT '0',
  `maxHP` smallint(6) unsigned NOT NULL DEFAULT '0',
  `maxMP` smallint(6) unsigned NOT NULL DEFAULT '0',
  `phy_attack` smallint(6) unsigned NOT NULL DEFAULT '0',
  `phy_defense` smallint(6) unsigned NOT NULL DEFAULT '0',
  `mag_attack` smallint(6) unsigned NOT NULL DEFAULT '0',
  `mag_defense` smallint(6) unsigned NOT NULL DEFAULT '0',
  `element_resist` tinyblob NOT NULL,
  `spec_property` tinyblob NOT NULL,
  `inven_weight` int(6) NOT NULL DEFAULT '0',
  `hp_regen` smallint(6) NOT NULL DEFAULT '0',
  `mp_regen` smallint(6) NOT NULL DEFAULT '0',
  `move_speed` smallint(6) unsigned NOT NULL DEFAULT '0',
  `attack_speed` smallint(6) unsigned NOT NULL DEFAULT '0',
  `cast_speed` smallint(6) unsigned NOT NULL DEFAULT '0',
  `hit_recovery` smallint(6) NOT NULL DEFAULT '0',
  `jump` smallint(6) NOT NULL DEFAULT '0',
  `charac_weight` int(11) NOT NULL DEFAULT '0',
  `fatigue` smallint(6) NOT NULL DEFAULT '0',
  `max_fatigue` smallint(6) NOT NULL DEFAULT '70',
  `premium_fatigue` smallint(6) NOT NULL DEFAULT '0',
  `max_premium_fatigue` smallint(6) NOT NULL DEFAULT '0',
  `create_time` datetime NOT NULL DEFAULT '0000-00-00 00:00:00',
  `last_play_time` datetime NOT NULL DEFAULT '0000-00-00 00:00:00',
  `dungeon_clear_point` int(11) NOT NULL DEFAULT '0',
  `delete_time` datetime NOT NULL DEFAULT '0000-00-00 00:00:00',
  `delete_flag` tinyint(4) NOT NULL DEFAULT '0',
  `guild_id` int(10) unsigned NOT NULL DEFAULT '0',
  `guild_right` tinyint(4) NOT NULL DEFAULT '0',
  `member_flag` tinyint(4) NOT NULL DEFAULT '0',
  `sex` tinyint(4) NOT NULL DEFAULT '1',
  `expert_job` tinyint(3) unsigned NOT NULL DEFAULT '0',
  `skill_tree_index` tinyint(4) NOT NULL DEFAULT '-1',
  `link_charac_no` int(10) unsigned NOT NULL DEFAULT '0',
  `event_charac_level` tinyint(4) NOT NULL DEFAULT '0',
  `guild_secede` tinyint(2) NOT NULL DEFAULT '0',
  `start_time` int(11) NOT NULL DEFAULT '0',
  `finish_time` int(11) NOT NULL DEFAULT '0',
  `competition_area` tinyint(2) NOT NULL DEFAULT '-1',
  `competition_period` tinyint(2) NOT NULL DEFAULT '-1',
  `mercenary_start_time` int(11) NOT NULL DEFAULT '0',
  `mercenary_finish_time` int(11) NOT NULL DEFAULT '0',
  `mercenary_area` tinyint(4) NOT NULL DEFAULT '-1',
  `mercenary_period` tinyint(4) NOT NULL DEFAULT '-1',
  `VIP` varchar(255) NOT NULL,
  PRIMARY KEY (`charac_no`),
  UNIQUE KEY `charac_name` (`charac_name`),
  KEY `charac_info_idx1` (`m_id`) USING BTREE,
  KEY `charac_info_idx2` (`exp`) USING BTREE,
  KEY `idx_guild_id` (`guild_id`) USING BTREE
) ENGINE=InnoDB DEFAULT CHARSET=utf8;

CREATE DATABASE IF NOT EXISTS d_taiwan;

USE d_taiwan;

CREATE TABLE `member_punish_info` (
  `m_id` int(11) NOT NULL DEFAULT '0',
  `punish_type` int(11) NOT NULL DEFAULT '0',
  `occ_time` datetime NOT NULL DEFAULT '0000-00-00 00:00:00',
  `punish_value` int(11) NOT NULL DEFAULT '0',
  `apply_flag` tinyint(4) NOT NULL DEFAULT '0',
  `start_time` datetime NOT NULL DEFAULT '0000-00-00 00:00:00',
  `end_time` datetime NOT NULL DEFAULT '0000-00-00 00:00:00',
  `admin_id` varchar(25) NOT NULL DEFAULT '',
  `reason` varchar(100) NOT NULL DEFAULT '',
  PRIMARY KEY (`m_id`,`punish_type`),
  KEY `idx1` (`occ_time`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;

CREATE DATABASE IF NOT EXISTS taiwan_cain_2nd;

USE taiwan_cain_2nd;

CREATE TABLE `postal` (
  `postal_id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `occ_time` datetime NOT NULL DEFAULT '0000-00-00 00:00:00',
  `send_charac_no` int(11) NOT NULL DEFAULT '0',
  `send_charac_name` varchar(20) NOT NULL DEFAULT '',
  `receive_charac_no` int(11) NOT NULL DEFAULT '0',
  `item_id` int(10) unsigned NOT NULL DEFAULT '0',
  `add_info` int(11) NOT NULL DEFAULT '0',
  `endurance` smallint(5) unsigned NOT NULL DEFAULT '0',
  `upgrade` tinyint(3) unsigned NOT NULL DEFAULT '0',
  `amplify_option` tinyint(3) unsigned NOT NULL DEFAULT '0',
  `amplify_value` mediumint(8) unsigned NOT NULL DEFAULT '0',
  `gold` int(10) unsigned NOT NULL DEFAULT '0',
  `receive_time` datetime NOT NULL DEFAULT '0000-00-00 00:00:00',
  `delete_flag` tinyint(3) unsigned NOT NULL DEFAULT '0',
  `avata_flag` tinyint(4) NOT NULL DEFAULT '0',
  `unlimit_flag` tinyint(4) NOT NULL DEFAULT '0',
  `seal_flag` tinyint(4) NOT NULL DEFAULT '0',
  `creature_flag` tinyint(4) NOT NULL DEFAULT '0',
  `postal` int(11) NOT NULL DEFAULT '0',
  `letter_id` int(11) NOT NULL DEFAULT '0',
  `extend_info` int(11) NOT NULL DEFAULT '0',
  `ipg_db_id` tinyint(4) NOT NULL DEFAULT '0',
  `ipg_transaction_id` int(11) NOT NULL DEFAULT '0',
  `ipg_nexon_id` varchar(32) NOT NULL DEFAULT '',
  `auction_id` bigint(20) unsigned NOT NULL DEFAULT '0',
  `random_option` varbinary(14) NOT NULL DEFAULT '',
  `seperate_upgrade` tinyint(3) unsigned NOT NULL DEFAULT '0',
  `type` tinyint(3) unsigned NOT NULL DEFAULT '0',
  `item_guid` varbinary(10) NOT NULL DEFAULT '',
  PRIMARY KEY (`postal_id`),
  KEY `idx_send_charac_no` (`send_charac_no`) USING BTREE,
  KEY `idx_receive_charac_no` (`receive_charac_no`) USING BTREE,
  KEY `idx_occ_time` (`occ_time`) USING BTREE
) ENGINE=InnoDB DEFAULT CHARSET=utf8;

CREATE DATABASE IF NOT EXISTS taiwan_cain_2nd;

USE taiwan_cain_2nd;

CREATE TABLE `letter` (
  `letter_id` int(11) NOT NULL AUTO_INCREMENT,
  `charac_no` int(11) NOT NULL DEFAULT '0',
  `send_charac_no` int(11) NOT NULL DEFAULT '0',
  `send_charac_name` varchar(20) NOT NULL DEFAULT '',
  `letter_text` varchar(255) NOT NULL DEFAULT '',
  `reg_date` datetime NOT NULL DEFAULT '0000-00-00 00:00:00',
  `stat` tinyint(4) NOT NULL DEFAULT '0',
  PRIMARY KEY (`letter_id`),
  KEY `idx_charac_no` (`charac_no`) USING BTREE,
  KEY `idx_reg_date` (`reg_date`) USING BTREE
) ENGINE=InnoDB DEFAULT CHARSET=utf8;

CREATE DATABASE IF NOT EXISTS taiwan_billing;

USE taiwan_billing;

CREATE TABLE `cash_cera` (
  `account` varchar(30) NOT NULL,
  `cera` int(10) unsigned NOT NULL,
  `mod_tran` bigint(20) unsigned NOT NULL,
  `mod_date` datetime NOT NULL,
  `reg_date` datetime NOT NULL,
  PRIMARY KEY (`account`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;

CREATE DATABASE IF NOT EXISTS taiwan_billing;

USE taiwan_billing;

CREATE TABLE `cash_cera_point` (
  `account` varchar(30) NOT NULL DEFAULT '',
  `cera_point` int(10) unsigned NOT NULL,
  `reg_date` datetime NOT NULL,
  `mod_date` datetime NOT NULL,
  PRIMARY KEY (`account`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;

CREATE DATABASE IF NOT EXISTS taiwan_login;

USE taiwan_login;

CREATE TABLE `login_account_3` (
  `m_id` int(10) unsigned NOT NULL DEFAULT '0',
  `m_channel_no` int(11) NOT NULL DEFAULT '0',
  `login_status` tinyint(1) NOT NULL DEFAULT '0',
  `last_login_date` datetime NOT NULL DEFAULT '0000-00-00 00:00:00',
  `login_ip` varchar(15) NOT NULL DEFAULT '',
  PRIMARY KEY (`m_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;

USE d_taiwan;

CREATE TABLE accounts(UID int NOT NULL PRIMARY KEY,accountname varchar(255) NOT NULL) ENGINE=MyISAM DEFAULT CHARSET=utf8;

USE taiwan_cain_2nd;
CREATE TABLE inventory (
 charac_no int NOT NULL PRIMARY KEY,
 money int unsigned NOT NULL DEFAULT 0,
 coin int unsigned NOT NULL DEFAULT 0,
 inventory_capacity int unsigned NOT NULL DEFAULT 0,
 inventory blob NOT NULL,
 equipslot blob NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8;

USE taiwan_cain;
CREATE TABLE charac_stat (
 charac_no int NOT NULL PRIMARY KEY,
 exp int NOT NULL DEFAULT 0,
 fatigue smallint NOT NULL DEFAULT 0,
 used_fatigue smallint NOT NULL DEFAULT 0,
 last_play_time datetime NOT NULL DEFAULT '0000-00-00 00:00:00'
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
