-- 010_decision_preferences
-- Financial Decision Intelligence: the two pieces of user state the
-- deterministic decision engine needs and that no existing table carries.
--
-- NOT added here (already present, deliberately reused):
--   * minimum balance to keep         -> accounts.safety_buffer       (002)
--   * savings goals                   -> savings_goals               (006)
--   * recurring commitments           -> recurring_transactions      (003)
--   * budgets / transactions / income -> existing tables
--
-- 1. accounts: payment preferences. The engine may only RECOMMEND a payment
--    method the user is willing to use, even when another is mathematically
--    safe. Defaults keep every existing account behaving as it does today:
--    partial payment allowed, installments NOT assumed, flexible-spending cuts
--    may be suggested.
--
-- 2. recurring_transactions.flexibility: which commitments the flexible-spending
--    engine is permitted to propose stopping or reducing. Defaults to
--    'essential' so NOTHING becomes cuttable without the user saying so.
--
-- FORMATTING CONTRACT (see backend/migrations_runner.py:split_statements):
-- the runner is line-oriented — a statement ends at a line whose stripped text
-- ends with ';'. Each PREPARE / EXECUTE / DEALLOCATE must therefore be on its
-- OWN line, exactly as in 001_transaction_direction.sql. Packing them onto one
-- line yields a single multi-statement string, which mysql-connector rejects
-- with "2014 (HY000): Commands out of sync".
--
-- Every block is guarded by information_schema, so re-running is safe.

-- accounts.accepts_partial_payment
SET @has := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'accounts' AND COLUMN_NAME = 'accepts_partial_payment');
SET @ddl := IF(@has = 0, 'ALTER TABLE accounts ADD COLUMN accepts_partial_payment BOOLEAN NOT NULL DEFAULT TRUE AFTER safety_buffer', 'SELECT 1');
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- accounts.accepts_installments
SET @has := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'accounts' AND COLUMN_NAME = 'accepts_installments');
SET @ddl := IF(@has = 0, 'ALTER TABLE accounts ADD COLUMN accepts_installments BOOLEAN NOT NULL DEFAULT FALSE AFTER accepts_partial_payment', 'SELECT 1');
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- accounts.allows_flexible_cuts
SET @has := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'accounts' AND COLUMN_NAME = 'allows_flexible_cuts');
SET @ddl := IF(@has = 0, 'ALTER TABLE accounts ADD COLUMN allows_flexible_cuts BOOLEAN NOT NULL DEFAULT TRUE AFTER accepts_installments', 'SELECT 1');
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- recurring_transactions.flexibility
SET @has := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'recurring_transactions' AND COLUMN_NAME = 'flexibility');
SET @ddl := IF(@has = 0, 'ALTER TABLE recurring_transactions ADD COLUMN flexibility ENUM(''essential'',''flexible'') NOT NULL DEFAULT ''essential'' AFTER active', 'SELECT 1');
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
