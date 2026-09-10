-- 007_bank_connections
-- Phase 15 — the user's trusted bank SMS source. User-scoped. Expendicure only
-- processes transaction notifications whose sender matches an ENABLED row here.
-- `ingest_token_hash` is the sha256 of a one-time companion token (shown once,
-- rotatable) so an Android/automation companion never holds a session JWT.
-- Review-only: there is deliberately NO auto-confirm — every detected event goes
-- to the user for Confirm / Edit / Ignore before any money reaches the twin.

CREATE TABLE IF NOT EXISTS bank_connections (
    id INT AUTO_INCREMENT PRIMARY KEY,
    student_id INT NOT NULL,
    bank_name VARCHAR(80) NOT NULL,
    sender_id VARCHAR(40) NOT NULL,
    masked_account VARCHAR(12) NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    ingest_token_hash CHAR(64) NULL,
    last_event_at TIMESTAMP NULL,
    events_detected INT NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_bank_conn_sender (student_id, sender_id),
    KEY idx_bank_conn_student (student_id, enabled),
    FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
);
