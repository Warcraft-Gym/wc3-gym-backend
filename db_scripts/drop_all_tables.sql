-- Safe drop-all script for GNL backend (MySQL)
-- WARNING: This will permanently delete all data. BACKUP before running.

SET FOREIGN_KEY_CHECKS = 0;

DROP TABLE IF EXISTS `fantasy_bets`;
DROP TABLE IF EXISTS `fantasy_team_player`;
DROP TABLE IF EXISTS `fantasy_teams`;
DROP TABLE IF EXISTS `user_team_season`;
DROP TABLE IF EXISTS `user_season_signup`;
DROP TABLE IF EXISTS `team_season`;
DROP TABLE IF EXISTS `map_season`;
DROP TABLE IF EXISTS `series`;
DROP TABLE IF EXISTS `matches`;
DROP TABLE IF EXISTS `w3cstats`;
DROP TABLE IF EXISTS `maps`;
DROP TABLE IF EXISTS `teams`;
DROP TABLE IF EXISTS `users`;
DROP TABLE IF EXISTS `seasons`;
DROP TABLE IF EXISTS `settings`;

SET FOREIGN_KEY_CHECKS = 1;

-- Usage examples:
-- Local mysql client:
--   mysql -u <user> -p -h <host> <database> < db_scripts/drop_all_tables.sql
-- With Docker (if MySQL container is running and accessible):
--   docker exec -i <mysql_container> mysql -u<user> -p<password> <database> < /path/in/container/db_scripts/drop_all_tables.sql

-- If you use the provided backend DB URL in `.env` (e.g. mysql+pymysql://user:pass@host:3306/GYM_BACKEND)
-- you can extract the database name and run the script against it. BACK UP your data first.
