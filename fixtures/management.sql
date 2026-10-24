CREATE DATABASE IF NOT EXISTS dnf_gm CHARACTER SET utf8mb4;
CREATE TABLE dnf_gm.operations (
 operation_id varchar(64) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
 fingerprint char(64) CHARACTER SET ascii NOT NULL,
 result longtext NOT NULL
) ENGINE=InnoDB;
CREATE TABLE dnf_gm.audit (
 id bigint unsigned NOT NULL AUTO_INCREMENT PRIMARY KEY,
 operation_id varchar(64) CHARACTER SET ascii NOT NULL UNIQUE,
 request_json longtext NOT NULL,
 result_json longtext NOT NULL
) ENGINE=InnoDB;
