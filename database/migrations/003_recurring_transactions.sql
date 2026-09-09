-- 003_recurring_transactions
-- Known repeating money movements (rent, subscriptions, allowance...). Used by
-- forecasting / affordability in later phases. 'source' distinguishes rows the
-- student entered from rows a detector proposes; 'confidence' is only set for
-- detected rows.

CREATE TABLE IF NOT EXISTS recurring_transactions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    student_id INT NOT NULL,
    label VARCHAR(100) NOT NULL,
    merchant_name VARCHAR(100) NOT NULL,
    amount DECIMAL(10,2) NOT NULL,
    direction ENUM('debit','credit') NOT NULL DEFAULT 'debit',
    cadence ENUM('weekly','monthly') NOT NULL,
    day_of_month INT NULL,
    weekday INT NULL,
    next_date DATE NOT NULL,
    source ENUM('user','detected') NOT NULL DEFAULT 'user',
    confidence DECIMAL(4,3) NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
);
