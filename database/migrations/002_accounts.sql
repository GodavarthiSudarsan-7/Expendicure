-- 002_accounts
-- One account row per student: opening balance + safety buffer + the date the
-- opening balance is stated as of. The live balance is derived (opening_balance
-- + credits - debits up to a date) by the finance repository, never stored.

CREATE TABLE IF NOT EXISTS accounts (
    id INT AUTO_INCREMENT PRIMARY KEY,
    student_id INT NOT NULL,
    opening_balance DECIMAL(10,2) NOT NULL DEFAULT 0.00,
    safety_buffer DECIMAL(10,2) NOT NULL DEFAULT 0.00,
    as_of_date DATE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_accounts_student (student_id),
    FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
);
