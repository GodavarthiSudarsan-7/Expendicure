-- 006_savings_goals
-- Per-student savings goals: a target amount by a target date, how much is
-- saved so far, and the monthly contribution the student plans to make.
-- The goal-progress and goal-impact engines (decision/) read these rows; they
-- are never written by the agent or by any simulation — only by the goals CRUD
-- API on the student's own behalf. 'current_amount' is the saved-so-far pot and
-- is kept <= 'target_amount' (no overfunding). Ownership is enforced by
-- student_id on every query; ON DELETE CASCADE keeps orphans out.

CREATE TABLE IF NOT EXISTS savings_goals (
    id INT AUTO_INCREMENT PRIMARY KEY,
    student_id INT NOT NULL,
    name VARCHAR(120) NOT NULL,
    target_amount DECIMAL(10,2) NOT NULL,
    current_amount DECIMAL(10,2) NOT NULL DEFAULT 0.00,
    monthly_contribution DECIMAL(10,2) NOT NULL DEFAULT 0.00,
    target_date DATE NOT NULL,
    status ENUM('active','archived','achieved') NOT NULL DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    KEY idx_savings_goals_student (student_id, status),
    FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
);
