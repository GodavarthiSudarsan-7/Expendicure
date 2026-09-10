-- Expendicure Seed Data
-- Sample data for testing the application

-- Insert sample accounts
INSERT INTO students (student_id, name, email) VALUES 
('U0000000001', 'John Doe', 'john.doe@example.com'),
('U0000000002', 'Jane Smith', 'jane.smith@example.com');

-- Insert default categories
INSERT INTO categories (name, is_default) VALUES 
('Food', TRUE),
('Rations', TRUE),
('Travel', TRUE),
('Books', TRUE),
('Rent', TRUE),
('Entertainment', TRUE),
('Health', TRUE),
('Other', TRUE);

-- Insert sample transactions for account id 1 (John Doe)
INSERT INTO transactions (student_id, amount, merchant_name, category_id, payment_date, payment_method, notes) VALUES 
(1, 15.50, 'Campus Cafe', 1, '2026-04-01', 'Credit Card', 'Lunch with friends'),
(1, 8.75, 'Bookstore', 4, '2026-04-02', 'Debit Card', 'Notebook for class'),
(1, 45.00, 'Gas Station', 3, '2026-04-03', 'Cash', 'Fuel for car'),
(1, 120.00, 'Amazon', 6, '2026-04-05', 'Credit Card', 'New video game'),
(1, 350.00, 'Apartment Rent', 5, '2026-04-01', 'Bank Transfer', 'Monthly rent'),
(1, 22.30, 'Grocery Store', 2, '2026-04-04', 'Debit Card', 'Weekly groceries'),
(1, 75.00, 'Doctor Visit', 7, '2026-04-06', 'Credit Card', 'Checkup'),
(1, 12.99, 'Netflix', 6, '2026-04-07', 'Credit Card', 'Monthly subscription');

-- Insert sample transactions for account id 2 (Jane Smith)
INSERT INTO transactions (student_id, amount, merchant_name, category_id, payment_date, payment_method, notes) VALUES 
(2, 9.50, 'Coffee Shop', 1, '2026-04-01', 'Cash', 'Morning coffee'),
(2, 25.00, 'Textbook Store', 4, '2026-04-02', 'Credit Card', 'Biology textbook'),
(2, 30.00, 'Bus Fare', 3, '2026-04-03', 'Cash', 'Weekly bus pass'),
(2, 18.75, 'Restaurant', 1, '2026-04-04', 'Debit Card', 'Dinner with roommate'),
(2, 400.00, 'Dormitory', 5, '2026-04-01', 'Bank Transfer', 'Monthly housing'),
(2, 15.20, 'Pharmacy', 7, '2026-04-05', 'Credit Card', 'Medication');

-- Insert sample budgets for account id 1 (John Doe) for April 2026
INSERT INTO budgets (student_id, category_id, monthly_limit, month) VALUES 
(1, 1, 200.00, '2026-04'), -- Food
(1, 2, 150.00, '2026-04'), -- Rations
(1, 3, 100.00, '2026-04'), -- Travel
(1, 4, 50.00, '2026-04'),  -- Books
(1, 5, 400.00, '2026-04'), -- Rent
(1, 6, 100.00, '2026-04'), -- Entertainment
(1, 7, 75.00, '2026-04'),  -- Health
(1, 8, 50.00, '2026-04');  -- Other

-- Insert sample budgets for account id 2 (Jane Smith) for April 2026
INSERT INTO budgets (student_id, category_id, monthly_limit, month) VALUES 
(2, 1, 150.00, '2026-04'), -- Food
(2, 2, 100.00, '2026-04'), -- Rations
(2, 3, 80.00, '2026-04'),  -- Travel
(2, 4, 75.00, '2026-04'),  -- Books
(2, 5, 420.00, '2026-04'), -- Rent
(2, 6, 75.00, '2026-04'),  -- Entertainment
(2, 7, 50.00, '2026-04'),  -- Health
(2, 8, 30.00, '2026-04');  -- Other