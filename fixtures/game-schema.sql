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
 village tinyint NOT NULL DEFAULT 1,
 village_prev tinyint NOT NULL DEFAULT 1,
 exp int NOT NULL DEFAULT 0,
 fatigue smallint NOT NULL DEFAULT 0,
 premium_fatigue smallint NOT NULL DEFAULT 0,
 used_fatigue smallint NOT NULL DEFAULT 0,
 expert_job_exp int NOT NULL DEFAULT 0,
 last_play_time datetime NOT NULL DEFAULT '0000-00-00 00:00:00'
) ENGINE=InnoDB DEFAULT CHARSET=utf8;

CREATE TABLE taiwan_cain_2nd.charac_item_lock_info (charac_no INT UNSIGNED PRIMARY KEY, item_lock_info BLOB) ENGINE=InnoDB;

CREATE TABLE d_taiwan.member_miles (
 m_id int NOT NULL PRIMARY KEY,
 miles int NOT NULL DEFAULT 0,
 daily_miles smallint NOT NULL DEFAULT 0
) ENGINE=InnoDB;

CREATE TABLE taiwan_cain_2nd.user_items (
 ui_id int NOT NULL AUTO_INCREMENT PRIMARY KEY,
 charac_no int NOT NULL DEFAULT 0,
 it_id int NOT NULL DEFAULT 0,
 slot int NOT NULL DEFAULT 0,
 clear_avatar_id int NOT NULL DEFAULT 0,
 color1 smallint NOT NULL DEFAULT 0,
 color2 smallint NOT NULL DEFAULT 0,
 jewel_socket blob NOT NULL,
 expire_date datetime NOT NULL,
 reg_date datetime NOT NULL,
 obtain_from tinyint DEFAULT NULL,
 stat tinyint unsigned NOT NULL DEFAULT 0
) ENGINE=InnoDB;

CREATE TABLE taiwan_cain_2nd.creature_items (
 ui_id int NOT NULL AUTO_INCREMENT PRIMARY KEY,
 charac_no int NOT NULL DEFAULT 0,
 it_id int unsigned NOT NULL DEFAULT 0,
 reg_date datetime NOT NULL,
 stomach int unsigned NOT NULL DEFAULT 0,
 creature_type tinyint NOT NULL DEFAULT 0
) ENGINE=InnoDB;

-- Synthetic empty fixtures matching the observed 1031 warehouse columns.
CREATE TABLE taiwan_cain_2nd.charac_inven_expand (
 charac_no int NOT NULL DEFAULT 0 PRIMARY KEY,
 cargo blob NOT NULL,
 cargo_capacity int unsigned NOT NULL DEFAULT 0,
 jewel blob NOT NULL,
 current_equipslot char(1) NOT NULL DEFAULT '',
 switch_equipslot blob NOT NULL,
 expand_equipslot blob NOT NULL,
 redeem_info blob NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8;

CREATE TABLE taiwan_cain.account_cargo (
 m_id bigint unsigned NOT NULL DEFAULT 0 PRIMARY KEY,
 money int unsigned NOT NULL DEFAULT 0,
 capacity tinyint unsigned NOT NULL DEFAULT 0,
 cargo blob NOT NULL,
 occ_time datetime NOT NULL DEFAULT '0000-00-00 00:00:00'
) ENGINE=InnoDB DEFAULT CHARSET=utf8;

-- Synthetic QF1031 PvE skill archive; no real learned-skill data.
-- Synthetic linkage tables required by the current minimal rename grants.
CREATE TABLE d_taiwan.guild_member (
 guild_id int NOT NULL,charac_no int NOT NULL,server_id int NOT NULL,m_id int NOT NULL,
 charac_name varchar(20) NOT NULL,PRIMARY KEY(guild_id,charac_no,server_id,m_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8 COLLATE=utf8_general_ci;
CREATE TABLE d_taiwan.guild_info (
 guild_id int NOT NULL,master_no int NOT NULL,server_id int NOT NULL,master_id int NOT NULL,
 master_name varchar(20) NOT NULL,PRIMARY KEY(guild_id,master_no,server_id,master_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8 COLLATE=utf8_general_ci;
CREATE TABLE d_taiwan.guild_recommend (
 no int NOT NULL,guild_id int NOT NULL,charac_no int NOT NULL,server_id int NOT NULL,
 charac_name varchar(20) NOT NULL,PRIMARY KEY(no,guild_id,charac_no,server_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8 COLLATE=utf8_general_ci;
CREATE TABLE d_taiwan.dnf_master_charac (
 m_id int NOT NULL,global_type int NOT NULL,server_id int NOT NULL,charac_no int NOT NULL,
 charac_name varchar(20) NOT NULL,PRIMARY KEY(m_id,global_type,server_id,charac_no)
) ENGINE=InnoDB DEFAULT CHARSET=utf8 COLLATE=utf8_general_ci;
CREATE TABLE taiwan_cain_2nd.charac_black_list (
 m_id int NOT NULL,charac_no int NOT NULL,charac_name varchar(20) NOT NULL,
 PRIMARY KEY(m_id,charac_no)
) ENGINE=InnoDB DEFAULT CHARSET=utf8 COLLATE=utf8_general_ci;

CREATE TABLE taiwan_cain_2nd.skill (
 charac_no int NOT NULL PRIMARY KEY,
 remain_sp int unsigned NOT NULL DEFAULT 0,
 sp_garbage int unsigned NOT NULL DEFAULT 0,
 used_sp int unsigned NOT NULL DEFAULT 0,
 skill_slot blob NOT NULL,
 request_sp blob NOT NULL,
 remain_sp_2nd int unsigned NOT NULL DEFAULT 0,
 skill_slot_2nd blob NOT NULL,
 request_sp_2nd blob NOT NULL,
 remain_sfp_2nd int unsigned NOT NULL DEFAULT 0,
 remain_sfp_1st int unsigned NOT NULL DEFAULT 0,
 skill_slot_lethe blob NOT NULL,
 skill_slot_lethe_2nd blob NOT NULL,
 lethe_flag tinyint NOT NULL DEFAULT 0,
 lethe_flag_2nd tinyint NOT NULL DEFAULT 0,
 skill_command blob NOT NULL,
 script_version tinyint NOT NULL DEFAULT 0
) ENGINE=InnoDB;
