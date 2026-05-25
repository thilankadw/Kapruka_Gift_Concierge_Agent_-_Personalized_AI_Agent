-- ============================================================================
-- KAPRUKA PRODUCT_DELIVERY_RULES SEED DATA
-- ============================================================================
-- Source JSON: data/logistics/product_delivery_rules.json
-- This file is generated from the JSON source of truth.
-- ============================================================================

INSERT INTO product_delivery_rules (
    product_type,
    fragile,
    temperature_control_required,
    same_day_allowed,
    minimum_notice_hours,
    max_delivery_distance_km
) VALUES
('cake', TRUE, FALSE, FALSE, 12, 315),
('flowers', FALSE, FALSE, FALSE, 24, 106),
('chocolates', FALSE, TRUE, TRUE, 24, 122),
('perfume', FALSE, FALSE, FALSE, 0, 64),
('gift_hamper', FALSE, TRUE, TRUE, 6, 138),
('electronics', FALSE, FALSE, FALSE, 2, 84),
('gift_voucher', FALSE, FALSE, FALSE, 24, 305),
('jewellery', TRUE, FALSE, TRUE, 0, 172),
('plants', TRUE, TRUE, FALSE, 24, 203),
('books', TRUE, TRUE, TRUE, 12, 129);
