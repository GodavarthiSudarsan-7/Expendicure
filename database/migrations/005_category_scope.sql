-- 005_category_scope
-- Give categories an owner: student_id NULL = global default category (the
-- existing seeded ones), student_id set = a category that student created.
-- The legacy global UNIQUE(name) index is replaced with UNIQUE(student_id,
-- name) so two students may each have a "Coffee" category. Global-name
-- uniqueness for NULL-owner rows is enforced in the categories route.
-- All statements are guarded via information_schema so the file is safe to
-- re-run by hand.

SET @has_col := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'categories' AND COLUMN_NAME = 'student_id');
SET @s := IF(@has_col = 0, 'ALTER TABLE categories ADD COLUMN student_id INT NULL AFTER name', 'SELECT 1');
PREPARE stmt FROM @s;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @has_legacy := (SELECT COUNT(*) FROM information_schema.STATISTICS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'categories' AND INDEX_NAME = 'name');
SET @s := IF(@has_legacy > 0, 'ALTER TABLE categories DROP INDEX name', 'SELECT 1');
PREPARE stmt FROM @s;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @has_uq := (SELECT COUNT(*) FROM information_schema.STATISTICS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'categories' AND INDEX_NAME = 'uq_categories_student_name');
SET @s := IF(@has_uq = 0, 'ALTER TABLE categories ADD UNIQUE KEY uq_categories_student_name (student_id, name)', 'SELECT 1');
PREPARE stmt FROM @s;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @has_fk := (SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'categories' AND CONSTRAINT_NAME = 'fk_categories_student');
SET @s := IF(@has_fk = 0, 'ALTER TABLE categories ADD CONSTRAINT fk_categories_student FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE', 'SELECT 1');
PREPARE stmt FROM @s;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
