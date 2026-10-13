-- Runs once, on first start of an empty MySQL volume.
-- `bms` and user `bms` are created by the image from MYSQL_DATABASE / MYSQL_USER.
CREATE DATABASE IF NOT EXISTS bms CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS bms_test CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
GRANT ALL PRIVILEGES ON bms.* TO 'bms'@'%';
GRANT ALL PRIVILEGES ON bms_test.* TO 'bms'@'%';
-- Concurrency tests create and drop their own throwaway database.
GRANT ALL PRIVILEGES ON bms_conc_test.* TO 'bms'@'%';
FLUSH PRIVILEGES;
