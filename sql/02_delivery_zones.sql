-- ============================================================================
-- KAPRUKA DELIVERY_ZONES SEED DATA
-- ============================================================================
-- Source JSON: data/logistics/delivery_zones.json
-- This file is generated from the JSON source of truth.
-- ============================================================================

INSERT INTO delivery_zones (
    district,
    delivery_available,
    same_day,
    express_available,
    minimum_notice_hours,
    max_daily_orders,
    active_couriers
) VALUES
('Colombo', TRUE, FALSE, TRUE, 24, 917, 88),
('Gampaha', TRUE, TRUE, FALSE, 2, 908, 405),
('Kalutara', TRUE, TRUE, TRUE, 12, 837, 299),
('Kandy', TRUE, FALSE, FALSE, 6, 398, 462),
('Matale', TRUE, TRUE, FALSE, 6, 353, 491),
('Nuwara Eliya', TRUE, TRUE, FALSE, 4, 1866, 439),
('Galle', TRUE, TRUE, FALSE, 6, 1439, 12),
('Matara', FALSE, FALSE, TRUE, 24, 1265, 34),
('Hambantota', TRUE, FALSE, TRUE, 6, 1249, 121),
('Jaffna', TRUE, FALSE, FALSE, 2, 101, 16),
('Kilinochchi', TRUE, FALSE, FALSE, 2, 1270, 412),
('Mannar', FALSE, TRUE, TRUE, 12, 1108, 153),
('Vavuniya', TRUE, FALSE, TRUE, 24, 1661, 409),
('Mullaitivu', TRUE, FALSE, FALSE, 24, 150, 339),
('Batticaloa', FALSE, FALSE, TRUE, 24, 198, 340),
('Ampara', TRUE, TRUE, FALSE, 2, 397, 308),
('Trincomalee', TRUE, TRUE, FALSE, 2, 1515, 232),
('Kurunegala', TRUE, FALSE, TRUE, 4, 458, 97),
('Puttalam', TRUE, FALSE, TRUE, 12, 306, 50),
('Anuradhapura', TRUE, FALSE, FALSE, 4, 356, 430),
('Polonnaruwa', FALSE, TRUE, TRUE, 2, 1206, 388),
('Badulla', TRUE, FALSE, TRUE, 24, 978, 500),
('Monaragala', FALSE, TRUE, TRUE, 24, 456, 268),
('Ratnapura', TRUE, TRUE, TRUE, 4, 273, 367),
('Kegalle', TRUE, FALSE, FALSE, 24, 1822, 261);
