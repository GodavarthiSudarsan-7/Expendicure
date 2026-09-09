-- 001_transaction_direction
-- Add debit/credit direction to transactions. Existing rows default to 'debit'
-- (they are all expenses in the pre-Phase-2 model). Guarded so it is safe to
-- re-run by hand.

SET @has_col := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'transactions' AND COLUMN_NAME = 'direction');
SET @ddl := IF(@has_col = 0, 'ALTER TABLE transactions ADD COLUMN direction ENUM(''debit'',''credit'') NOT NULL DEFAULT ''debit'' AFTER amount', 'SELECT 1');
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
