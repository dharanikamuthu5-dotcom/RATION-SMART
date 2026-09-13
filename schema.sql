-- ==========================================================
-- RationSmart AI - Relational Database Schema (MySQL 8.0+)
-- Smart Ration Distribution. Predictive. Transparent. Citizen-Centric.
-- ==========================================================

CREATE DATABASE IF NOT EXISTS rationsmart_ai;
USE rationsmart_ai;

-- 1. USERS TABLE (Role-based access: citizen, shop_staff, gov_admin)
CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(64) NOT NULL UNIQUE,
    email VARCHAR(120) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    full_name VARCHAR(120) NOT NULL,
    role ENUM('citizen', 'shop_staff', 'gov_admin') NOT NULL DEFAULT 'citizen',
    ration_card_no VARCHAR(32) UNIQUE NULL,
    phone VARCHAR(20) NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 2. RATION FAIR PRICE SHOPS (FPS)
CREATE TABLE IF NOT EXISTS ration_shops (
    id INT AUTO_INCREMENT PRIMARY KEY,
    shop_code VARCHAR(32) NOT NULL UNIQUE,
    shop_name VARCHAR(150) NOT NULL,
    address TEXT NOT NULL,
    zone VARCHAR(64) NOT NULL,
    staff_user_id INT NULL,
    contact_number VARCHAR(20) NULL,
    status ENUM('active', 'inactive', 'maintenance') DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_shops_staff FOREIGN KEY (staff_user_id) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 3. RATION ITEMS / COMMODITIES (Rice, Wheat, Sugar)
CREATE TABLE IF NOT EXISTS ration_items (
    id INT AUTO_INCREMENT PRIMARY KEY,
    item_code VARCHAR(32) NOT NULL UNIQUE,
    item_name VARCHAR(100) NOT NULL,
    unit VARCHAR(16) NOT NULL DEFAULT 'kg',
    monthly_quota_per_beneficiary DECIMAL(10,2) NOT NULL,
    unit_price DECIMAL(10,2) NOT NULL DEFAULT 0.00,
    status ENUM('active', 'inactive') DEFAULT 'active'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 4. INVENTORY STOCK PER SHOP
CREATE TABLE IF NOT EXISTS stock (
    id INT AUTO_INCREMENT PRIMARY KEY,
    shop_id INT NOT NULL,
    item_id INT NOT NULL,
    current_stock DECIMAL(12,2) NOT NULL DEFAULT 0.00,
    reserved_stock DECIMAL(12,2) NOT NULL DEFAULT 0.00,
    min_threshold DECIMAL(12,2) NOT NULL DEFAULT 100.00,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_shop_item (shop_id, item_id),
    CONSTRAINT fk_stock_shop FOREIGN KEY (shop_id) REFERENCES ration_shops(id) ON DELETE CASCADE,
    CONSTRAINT fk_stock_item FOREIGN KEY (item_id) REFERENCES ration_items(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 5. BOOKINGS / DIGITAL SLOTS
CREATE TABLE IF NOT EXISTS bookings (
    id INT AUTO_INCREMENT PRIMARY KEY,
    booking_ref VARCHAR(32) NOT NULL UNIQUE,
    user_id INT NOT NULL,
    shop_id INT NOT NULL,
    booking_date DATE NOT NULL,
    time_slot VARCHAR(32) NOT NULL,
    status ENUM('Pending', 'Approved', 'Completed', 'Cancelled') NOT NULL DEFAULT 'Pending',
    qr_code_data VARCHAR(64) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_bookings_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT fk_bookings_shop FOREIGN KEY (shop_id) REFERENCES ration_shops(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 6. BOOKING ITEMS (Line items per booking)
CREATE TABLE IF NOT EXISTS booking_items (
    id INT AUTO_INCREMENT PRIMARY KEY,
    booking_id INT NOT NULL,
    item_id INT NOT NULL,
    quantity DECIMAL(10,2) NOT NULL,
    unit VARCHAR(16) NOT NULL,
    CONSTRAINT fk_bi_booking FOREIGN KEY (booking_id) REFERENCES bookings(id) ON DELETE CASCADE,
    CONSTRAINT fk_bi_item FOREIGN KEY (item_id) REFERENCES ration_items(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 7. HISTORICAL QUEUE DATA (Used for AI Training & Congestion Analytics)
CREATE TABLE IF NOT EXISTS queue_data (
    id INT AUTO_INCREMENT PRIMARY KEY,
    shop_id INT NOT NULL,
    day_of_week INT NOT NULL COMMENT '0=Monday, 6=Sunday',
    hour INT NOT NULL COMMENT '8 to 18',
    active_bookings INT NOT NULL DEFAULT 0,
    actual_queue_count INT NOT NULL DEFAULT 0,
    avg_wait_time_minutes INT NOT NULL DEFAULT 0,
    recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_queue_shop FOREIGN KEY (shop_id) REFERENCES ration_shops(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 8. AI PREDICTIONS LOG TABLE
CREATE TABLE IF NOT EXISTS ai_predictions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    shop_id INT NOT NULL,
    prediction_type ENUM('queue', 'stock') NOT NULL,
    input_params TEXT NOT NULL,
    predicted_value TEXT NOT NULL,
    confidence_score DECIMAL(5,2) DEFAULT 0.90,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_ai_shop FOREIGN KEY (shop_id) REFERENCES ration_shops(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ==========================================================
-- REALISTIC DEMO DATA
-- Demo Credentials:
-- Citizen:    citizen@rationsmart.gov   / citizen123  (RC-DL-98472)
-- Shop Staff: staff@rationsmart.gov     / staff123    (FPS #104)
-- Gov Admin:  admin@rationsmart.gov     / admin123
-- ==========================================================

INSERT INTO users (id, username, email, password_hash, full_name, role, ration_card_no, phone) VALUES
(1, 'citizen', 'citizen@rationsmart.gov', 'scrypt:32768:8:1$qApvAcxCPgtPbC6D$35b13b4ead99d075170e74e40e1f7962ef6229d46b81adb6ba34305b6611bae605946d26fe9e429ee158c6e75a59463a68acb91c9b9d9fefc18907549b6a9564', 'Aarav Sharma', 'citizen', 'RC-DL-98472', '+91 98765 43210'),
(2, 'shopstaff', 'staff@rationsmart.gov', 'scrypt:32768:8:1$IPdFfiHSxlXUungP$5642e2f0435de3a9124aa1eb4287f7c6f2bc40d8d3e988c5c232ec3d5e7de9d9194330fbf58bef8615a27158140979cde3a0f8ccc3e8d3ce23704db101170f13', 'Rajesh Patel', 'shop_staff', NULL, '+91 98111 22334'),
(3, 'govadmin', 'admin@rationsmart.gov', 'scrypt:32768:8:1$O1X4QDuJtR5jqMAM$de96b34e8a97143196f8303dea9ec62717f8c8bc63994ac8f97862e2f65fa9a7a7ff00ec3120bf3ee82d4c1797aa88f23b125d5c32fc9121142a71cdf726e3d3', 'Dr. Meenakshi Sundaram (IAS)', 'gov_admin', NULL, '+91 98222 33445')
ON DUPLICATE KEY UPDATE full_name = VALUES(full_name);

INSERT INTO ration_shops (id, shop_code, shop_name, address, zone, staff_user_id, contact_number, status) VALUES
(1, 'FPS-DEL-104', 'Central Fair Price Shop #104', 'Sector 4, Connaught Place, New Delhi', 'Central Zone', 2, '+91 11 2334 5678', 'active'),
(2, 'FPS-DEL-101', 'North Municipal FPS #101', 'Civil Lines, Model Town, Delhi', 'North Zone', NULL, '+91 11 2745 1290', 'active'),
(3, 'FPS-DEL-205', 'South Subsidized Depot #205', 'Hauz Khas Market, New Delhi', 'South Zone', NULL, '+91 11 2656 7890', 'active')
ON DUPLICATE KEY UPDATE shop_name = VALUES(shop_name);

INSERT INTO ration_items (id, item_code, item_name, unit, monthly_quota_per_beneficiary, unit_price, status) VALUES
(1, 'COMM-RICE', 'Rice (Boiled/Sona Masoori)', 'kg', 5.00, 3.00, 'active'),
(2, 'COMM-WHEAT', 'Wheat (Fortified Atta)', 'kg', 5.00, 2.00, 'active'),
(3, 'COMM-SUGAR', 'Refined Sugar', 'kg', 1.00, 13.50, 'active')
ON DUPLICATE KEY UPDATE item_name = VALUES(item_name);

INSERT INTO stock (shop_id, item_id, current_stock, reserved_stock, min_threshold) VALUES
(1, 1, 850.00, 45.00, 250.00), -- Rice: 850 kg
(1, 2, 620.00, 35.00, 200.00), -- Wheat: 620 kg
(1, 3, 140.00, 12.00, 80.00),  -- Sugar: 140 kg
(2, 1, 420.00, 20.00, 200.00),
(2, 2, 190.00, 30.00, 200.00), -- Low wheat alert for shop 2
(2, 3, 65.00, 10.00, 70.00),   -- Low sugar alert for shop 2
(3, 1, 1200.00, 50.00, 300.00),
(3, 2, 980.00, 40.00, 250.00),
(3, 3, 240.00, 15.00, 100.00)
ON DUPLICATE KEY UPDATE current_stock = VALUES(current_stock);

-- Seed an active booking for demonstration
INSERT INTO bookings (id, booking_ref, user_id, shop_id, booking_date, time_slot, status, qr_code_data) VALUES
(1, 'RS-2026-8491', 1, 1, CURDATE(), '10:00 - 11:00 AM', 'Approved', 'RS-2026-8491')
ON DUPLICATE KEY UPDATE booking_ref = VALUES(booking_ref);

INSERT INTO booking_items (booking_id, item_id, quantity, unit) VALUES
(1, 1, 5.00, 'kg'),
(1, 2, 5.00, 'kg'),
(1, 3, 1.00, 'kg')
ON DUPLICATE KEY UPDATE quantity = VALUES(quantity);

-- Seed Historical Queue Samples for Shop 1 (Central FPS)
INSERT INTO queue_data (shop_id, day_of_week, hour, active_bookings, actual_queue_count, avg_wait_time_minutes) VALUES
(1, 0, 9, 6, 8, 22),
(1, 0, 10, 12, 16, 45),
(1, 0, 11, 14, 18, 50),
(1, 0, 12, 9, 11, 28),
(1, 0, 14, 4, 5, 12),
(1, 0, 15, 7, 8, 20),
(1, 0, 16, 11, 14, 38),
(1, 1, 9, 5, 6, 16),
(1, 1, 10, 10, 13, 35),
(1, 1, 11, 12, 15, 40),
(1, 1, 12, 8, 9, 24),
(1, 1, 14, 3, 4, 10),
(1, 1, 15, 6, 7, 18),
(1, 1, 16, 10, 12, 32),
(1, 5, 10, 18, 24, 65),
(1, 5, 11, 22, 28, 75),
(1, 5, 12, 16, 20, 52),
(1, 5, 14, 8, 9, 24),
(1, 5, 15, 12, 15, 38),
(1, 5, 16, 19, 25, 68);

-- Seed initial AI Prediction
INSERT INTO ai_predictions (shop_id, prediction_type, input_params, predicted_value, confidence_score) VALUES
(1, 'queue', '{"day": 0, "hour": 10, "bookings": 12}', '{"predicted_queue": 15, "wait_time_min": 42, "recommended_slot": "14:00 - 15:00"}', 0.93),
(1, 'stock', '{"shop_id": 1, "item": "Rice"}', '{"burn_rate_daily": 42.5, "days_remaining": 20, "shortage_risk": "Optimal"}', 0.95);
