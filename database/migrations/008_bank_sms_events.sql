-- 008_bank_sms_events
-- Phase 15 — provenance + review state for transactions detected from bank SMS.
-- This is NOT a parallel transaction store: the money only ever lives in the
-- existing `transactions` table. This table holds the structured fields the
-- deterministic parser extracted, the dedup fingerprint, and the review status.
-- The raw SMS body is NEVER stored here or anywhere.
--
-- Lifecycle (review-only): needs_confirmation | needs_review  --(user)-->
--   confirmed (transaction_id set, row inserted into `transactions`) | ignored.
-- 'rejected' is used for events that failed sender/format checks and are kept
-- only as a lightweight audit count; they carry no extracted financial fields.

CREATE TABLE IF NOT EXISTS bank_sms_events (
    id INT AUTO_INCREMENT PRIMARY KEY,
    student_id INT NOT NULL,
    connection_id INT NOT NULL,
    status ENUM('needs_confirmation','needs_review','confirmed','ignored','rejected') NOT NULL DEFAULT 'needs_confirmation',
    direction ENUM('debit','credit') NULL,
    amount DECIMAL(10,2) NULL,
    occurred_on DATE NULL,
    occurred_at DATETIME NULL,
    merchant VARCHAR(120) NULL,
    masked_account VARCHAR(12) NULL,
    bank_ref_id VARCHAR(64) NULL,
    fingerprint CHAR(64) NOT NULL,
    detect_reason VARCHAR(160) NULL,
    template_id VARCHAR(40) NULL,
    transaction_id INT NULL,
    received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    resolved_at TIMESTAMP NULL,
    UNIQUE KEY uq_event_fingerprint (connection_id, fingerprint),
    KEY idx_event_student_status (student_id, status),
    FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE,
    FOREIGN KEY (connection_id) REFERENCES bank_connections(id) ON DELETE CASCADE
);
