-- =============================================================================
-- KAPRUKA CRM USERS SEED DATA
-- =============================================================================
-- Sample users for testing:
-- - Semantic memory extraction
-- - Preference updates
-- - Personalized gift recommendations
-- - Delivery/location-based recommendations
-- =============================================================================

INSERT INTO users (
    user_id,
    external_user_id,
    full_name,
    email,
    phone,
    district,
    active,
    created_at,
    updated_at
) VALUES
(
    'usr_001',
    '94771234567',
    'Thilanka Wijesingha',
    'thilanka@gmail.com',
    '+94771234567',
    'Colombo',
    TRUE,
    EXTRACT(EPOCH FROM NOW()),
    EXTRACT(EPOCH FROM NOW())
),

(
    'usr_002',
    '94772345678',
    'Nethmi Perera',
    'nethmi.perera@gmail.com',
    '+94772345678',
    'Kandy',
    TRUE,
    EXTRACT(EPOCH FROM NOW()),
    EXTRACT(EPOCH FROM NOW())
),

(
    'usr_003',
    '94773456789',
    'Kasun Silva',
    'kasun.silva@gmail.com',
    '+94773456789',
    'Galle',
    TRUE,
    EXTRACT(EPOCH FROM NOW()),
    EXTRACT(EPOCH FROM NOW())
),

(
    'usr_004',
    '94774567890',
    'Sanduni Fernando',
    'sanduni.fernando@gmail.com',
    '+94774567890',
    'Kurunegala',
    TRUE,
    EXTRACT(EPOCH FROM NOW()),
    EXTRACT(EPOCH FROM NOW())
),

(
    'usr_005',
    '94775678901',
    'Amila Jayawardena',
    'amila.j@gmail.com',
    '+94775678901',
    'Jaffna',
    TRUE,
    EXTRACT(EPOCH FROM NOW()),
    EXTRACT(EPOCH FROM NOW())
),

(
    'usr_006',
    '94776789012',
    'Chamodi Wickramasinghe',
    'chamodi.w@gmail.com',
    '+94776789012',
    'Matara',
    TRUE,
    EXTRACT(EPOCH FROM NOW()),
    EXTRACT(EPOCH FROM NOW())
),

(
    'usr_007',
    '94777890123',
    'Dinesh Rajapaksa',
    'dinesh.r@gmail.com',
    '+94777890123',
    'Negombo',
    TRUE,
    EXTRACT(EPOCH FROM NOW()),
    EXTRACT(EPOCH FROM NOW())
),

(
    'usr_008',
    '94778901234',
    'Tharushi De Silva',
    'tharushi.ds@gmail.com',
    '+94778901234',
    'Anuradhapura',
    TRUE,
    EXTRACT(EPOCH FROM NOW()),
    EXTRACT(EPOCH FROM NOW())
),

(
    'usr_009',
    '94779012345',
    'Sahan Gunawardena',
    'sahan.g@gmail.com',
    '+94779012345',
    'Batticaloa',
    TRUE,
    EXTRACT(EPOCH FROM NOW()),
    EXTRACT(EPOCH FROM NOW())
),

(
    'usr_010',
    '94770123456',
    'Madhavi Senanayake',
    'madhavi.s@gmail.com',
    '+94770123456',
    'Ratnapura',
    TRUE,
    EXTRACT(EPOCH FROM NOW()),
    EXTRACT(EPOCH FROM NOW())
);