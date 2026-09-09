-- 004_categorization_rules
-- Deterministic "merchant text -> category" rules. A NULL student_id is a global
-- default rule; a set student_id is that student's personal override. The
-- matching engine that consumes these arrives in a later phase; Phase 2 only
-- provides the table, model and CRUD API.

CREATE TABLE IF NOT EXISTS categorization_rules (
    id INT AUTO_INCREMENT PRIMARY KEY,
    student_id INT NULL,
    match_type ENUM('contains','equals') NOT NULL DEFAULT 'contains',
    pattern VARCHAR(120) NOT NULL,
    category_id INT NOT NULL,
    priority INT NOT NULL DEFAULT 100,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE,
    FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE CASCADE
);
