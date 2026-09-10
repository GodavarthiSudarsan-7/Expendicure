-- 009_user_mobile_number
-- Product repositioning: Expendicure is a general personal-finance product, not
-- a student app. Account signup now collects a mobile number (the user's
-- contact identity) instead of a user-facing "Student ID". This migration:
--   1. adds accounts.mobile_number  (VARCHAR(20), nullable, UNIQUE — NULLs do not
--      collide in MySQL, so existing rows without a number are fine),
--   2. relaxes accounts.email to NULL so signup can proceed without one.
--
-- The internal ``students`` table / ``student_id`` ownership key is unchanged:
-- it is only an internal owner id, never shown to users. ``student_id`` (the
-- VARCHAR column) is now an opaque, auto-generated account reference.
-- All statements are guarded so the file is safe to re-run by hand.

SET @has_mobile := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'students' AND COLUMN_NAME = 'mobile_number');
SET @ddl := IF(@has_mobile = 0, 'ALTER TABLE students ADD COLUMN mobile_number VARCHAR(20) NULL AFTER email', 'SELECT 1');
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @has_uq := (SELECT COUNT(*) FROM information_schema.STATISTICS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'students' AND INDEX_NAME = 'uq_students_mobile');
SET @ddl := IF(@has_uq = 0, 'ALTER TABLE students ADD UNIQUE KEY uq_students_mobile (mobile_number)', 'SELECT 1');
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @email_nullable := (SELECT IS_NULLABLE FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'students' AND COLUMN_NAME = 'email');
SET @ddl := IF(@email_nullable = 'NO', 'ALTER TABLE students MODIFY email VARCHAR(100) NULL', 'SELECT 1');
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
