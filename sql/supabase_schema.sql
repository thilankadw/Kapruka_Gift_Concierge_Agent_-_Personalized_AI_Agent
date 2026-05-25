-- ============================================================================
-- Supabase Schema: Kapruka Gift-Concierge Agent
-- PostgreSQL 15+ with pgvector extension
-- ============================================================================
--
-- Project: AEE Bootcamp Mini Project 03 - Kapruka Gift-Concierge Agent
-- Embedding Model: text-embedding-3-small
-- Vector Dimensions: 1536
--
-- Architecture:
-- 1. Supabase Postgres + pgvector stores the agent memory system.
-- 2. CRM is domain-specific. For this project, users plus logistics tables are needed.
-- 3. Kapruka product catalog is NOT stored here. Product metadata is vectorized
--    and stored in Qdrant for RAG-based product retrieval.
--
-- ============================================================================

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================================
-- SHORT-TERM MEMORY
-- Stores recent conversation turns for the current user session.
-- This is useful for live context, but it can expire using ttl_at.
-- ============================================================================

CREATE TABLE IF NOT EXISTS st_turns (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    ttl_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_st_turns_user_session
ON st_turns (user_id, session_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_st_turns_ttl
ON st_turns (ttl_at)
WHERE ttl_at IS NOT NULL;

COMMENT ON TABLE st_turns IS 'Short-term conversation memory for Kapruka agent sessions';
COMMENT ON COLUMN st_turns.user_id IS 'Canonical CRM user identifier linked to users.user_id';
COMMENT ON COLUMN st_turns.session_id IS 'Conversation session identifier';
COMMENT ON COLUMN st_turns.ttl_at IS 'Optional expiry time for short-term memory cleanup';

-- ============================================================================
-- LONG-TERM SEMANTIC MEMORY
-- Stores durable user facts, preferences, allergies, budget preferences,
-- delivery preferences, and other personal gift-selection facts.
--
-- Example:
-- text: User loves dark chocolate.
-- tags: ["preference", "food", "chocolate"]
-- ============================================================================

CREATE TABLE IF NOT EXISTS mem_facts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL,
    text TEXT NOT NULL,
    embedding vector(1536),
    score REAL NOT NULL CHECK (score >= 0 AND score <= 1),
    tags JSONB DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_used_at TIMESTAMPTZ DEFAULT NOW(),
    ttl_at TIMESTAMPTZ,
    pin BOOLEAN DEFAULT FALSE,
    deleted BOOLEAN DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_mem_facts_user_id
ON mem_facts(user_id);

CREATE INDEX IF NOT EXISTS idx_mem_facts_score
ON mem_facts(score DESC);

CREATE INDEX IF NOT EXISTS idx_mem_facts_deleted
ON mem_facts(deleted)
WHERE deleted = FALSE;

CREATE INDEX IF NOT EXISTS idx_mem_facts_ttl
ON mem_facts(ttl_at)
WHERE ttl_at IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_mem_facts_tags
ON mem_facts USING gin(tags);

-- IVFFlat index for semantic fact retrieval using cosine distance.
CREATE INDEX IF NOT EXISTS idx_mem_facts_embedding
ON mem_facts USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

COMMENT ON TABLE mem_facts IS 'Long-term semantic memory facts for Kapruka user preferences and constraints';
COMMENT ON COLUMN mem_facts.text IS 'Natural language memory fact, such as User loves dark chocolate';
COMMENT ON COLUMN mem_facts.score IS 'Confidence or relevance score between 0 and 1';
COMMENT ON COLUMN mem_facts.tags IS 'JSON tags such as preference, allergy, budget, delivery, occasion';
COMMENT ON COLUMN mem_facts.pin IS 'Pinned facts should be retained unless explicitly deleted';
COMMENT ON COLUMN mem_facts.deleted IS 'Soft delete flag for memory cleanup or correction';

-- Semantic search helper for user facts.
CREATE OR REPLACE FUNCTION search_mem_facts(
    query_embedding vector(1536),
    query_user_id TEXT,
    match_threshold FLOAT DEFAULT 0.3,
    match_count INT DEFAULT 10
)
RETURNS TABLE (
    id UUID,
    user_id TEXT,
    text TEXT,
    score REAL,
    tags JSONB,
    similarity FLOAT
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        f.id,
        f.user_id,
        f.text,
        f.score,
        f.tags,
        1 - (f.embedding <=> query_embedding) AS similarity
    FROM mem_facts f
    WHERE f.user_id = query_user_id
        AND f.deleted = FALSE
        AND (f.ttl_at IS NULL OR f.ttl_at > NOW())
        AND 1 - (f.embedding <=> query_embedding) >= match_threshold
    ORDER BY f.embedding <=> query_embedding
    LIMIT match_count;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION search_mem_facts IS 'Semantic search over Kapruka user memory facts using cosine similarity';

-- ============================================================================
-- LONG-TERM EPISODIC MEMORY
-- Stores summarized past gift conversations or recommendation sessions.
--
-- Example:
-- summary: User searched for birthday gifts under Rs. 5000 and rejected nut cakes.
-- topic_tags: ["birthday", "budget", "allergy", "cake"]
-- ============================================================================

CREATE TABLE IF NOT EXISTS mem_episodes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    summary TEXT NOT NULL,
    summary_embedding vector(1536),
    topic_tags JSONB DEFAULT '[]'::jsonb,
    start_at TIMESTAMPTZ NOT NULL,
    end_at TIMESTAMPTZ NOT NULL,
    turn_count INTEGER NOT NULL CHECK (turn_count > 0),
    turns JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_mem_episodes_user_id
ON mem_episodes(user_id);

CREATE INDEX IF NOT EXISTS idx_mem_episodes_session_id
ON mem_episodes(session_id);

CREATE INDEX IF NOT EXISTS idx_mem_episodes_start_at
ON mem_episodes(start_at DESC);

CREATE INDEX IF NOT EXISTS idx_mem_episodes_created_at
ON mem_episodes(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_mem_episodes_topic_tags
ON mem_episodes USING gin(topic_tags);

CREATE INDEX IF NOT EXISTS idx_mem_episodes_embedding
ON mem_episodes USING ivfflat (summary_embedding vector_cosine_ops) WITH (lists = 100);

COMMENT ON TABLE mem_episodes IS 'Long-term episodic memory for previous Kapruka gift conversations';
COMMENT ON COLUMN mem_episodes.summary IS 'Conversation/session summary created after a gift recommendation interaction';
COMMENT ON COLUMN mem_episodes.turns IS 'Full conversation turns stored as JSON for traceability';
COMMENT ON COLUMN mem_episodes.topic_tags IS 'Topics such as birthday, chocolate, delivery, allergy, budget';

-- Semantic search helper for past episodes.
CREATE OR REPLACE FUNCTION search_mem_episodes(
    query_embedding vector(1536),
    query_user_id TEXT,
    match_threshold FLOAT DEFAULT 0.3,
    match_count INT DEFAULT 10
)
RETURNS TABLE (
    id UUID,
    user_id TEXT,
    session_id TEXT,
    summary TEXT,
    topic_tags JSONB,
    start_at TIMESTAMPTZ,
    end_at TIMESTAMPTZ,
    turn_count INTEGER,
    similarity FLOAT
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        e.id,
        e.user_id,
        e.session_id,
        e.summary,
        e.topic_tags,
        e.start_at,
        e.end_at,
        e.turn_count,
        1 - (e.summary_embedding <=> query_embedding) AS similarity
    FROM mem_episodes e
    WHERE e.user_id = query_user_id
        AND 1 - (e.summary_embedding <=> query_embedding) >= match_threshold
    ORDER BY e.summary_embedding <=> query_embedding
    LIMIT match_count;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION search_mem_episodes IS 'Semantic search over previous Kapruka gift recommendation episodes';

-- ============================================================================
-- PROCEDURAL MEMORY
-- Stores reusable workflows used by the Kapruka concierge agent.
--
-- Example procedures:
-- 1. preference_extraction_flow
-- 2. gift_recommendation_flow
-- 3. delivery_validation_flow
-- 4. allergy_safety_reflection_flow
-- ============================================================================

CREATE TABLE IF NOT EXISTS mem_procedures (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL,
    context_when TEXT,
    steps JSONB NOT NULL,
    conditions JSONB,
    examples JSONB,
    embedding vector(1536),
    category TEXT,
    active BOOLEAN DEFAULT TRUE,
    version INTEGER DEFAULT 1,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_mem_procedures_name
ON mem_procedures(name);

CREATE INDEX IF NOT EXISTS idx_mem_procedures_category
ON mem_procedures(category);

CREATE INDEX IF NOT EXISTS idx_mem_procedures_active
ON mem_procedures(active)
WHERE active = TRUE;

CREATE INDEX IF NOT EXISTS idx_mem_procedures_embedding
ON mem_procedures USING ivfflat (embedding vector_cosine_ops) WITH (lists = 50);

COMMENT ON TABLE mem_procedures IS 'Procedural memory for Kapruka agent workflows and task execution patterns';
COMMENT ON COLUMN mem_procedures.steps IS 'Ordered workflow steps stored as JSON';
COMMENT ON COLUMN mem_procedures.category IS 'Procedure category such as preference_update, catalog_search, logistics, reflection';

-- Semantic search helper for procedures.
CREATE OR REPLACE FUNCTION search_mem_procedures(
    query_embedding vector(1536),
    match_threshold FLOAT DEFAULT 0.3,
    match_count INT DEFAULT 5
)
RETURNS TABLE (
    id UUID,
    name TEXT,
    description TEXT,
    steps JSONB,
    category TEXT,
    similarity FLOAT
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        p.id,
        p.name,
        p.description,
        p.steps,
        p.category,
        1 - (p.embedding <=> query_embedding) AS similarity
    FROM mem_procedures p
    WHERE p.active = TRUE
        AND 1 - (p.embedding <=> query_embedding) >= match_threshold
    ORDER BY p.embedding <=> query_embedding
    LIMIT match_count;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION search_mem_procedures IS 'Semantic search over Kapruka procedural memory workflows';

-- ============================================================================
-- CRM: USERS
-- Core CRM table for the Kapruka project.
--
-- Product data is intentionally excluded from the CRM because the product
-- catalog is vectorized and stored in Qdrant for RAG retrieval.
-- ============================================================================

CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    external_user_id TEXT UNIQUE,
    full_name TEXT,
    email TEXT UNIQUE,
    phone TEXT,
    district TEXT,
    province TEXT,
    address TEXT,
    notes TEXT,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

ALTER TABLE users ADD COLUMN IF NOT EXISTS province TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS address TEXT;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'users'
          AND column_name = 'active'
          AND data_type <> 'boolean'
    ) THEN
        ALTER TABLE users
        ALTER COLUMN active DROP DEFAULT;

        ALTER TABLE users
        ALTER COLUMN active TYPE BOOLEAN
        USING (active <> 0);

        ALTER TABLE users
        ALTER COLUMN active SET DEFAULT TRUE;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_users_external_user_id
ON users(external_user_id);

CREATE INDEX IF NOT EXISTS idx_users_email
ON users(email);

CREATE INDEX IF NOT EXISTS idx_users_phone
ON users(phone);

CREATE INDEX IF NOT EXISTS idx_users_district
ON users(district);

COMMENT ON TABLE users IS 'Kapruka CRM user profiles. Preferences are stored in mem_facts, not in this table';
COMMENT ON COLUMN users.external_user_id IS 'External chat or application identifier if available';
COMMENT ON COLUMN users.district IS 'Default Sri Lankan delivery district or user location';
COMMENT ON COLUMN users.province IS 'Optional Sri Lankan province for the user profile';
COMMENT ON COLUMN users.address IS 'Optional delivery address or address note';
COMMENT ON COLUMN users.notes IS 'Optional CRM notes. Durable preferences should be saved in mem_facts';

-- ============================================================================
-- LOGISTICS: DELIVERY ZONES
-- Structured district-level delivery configuration sourced from JSON assets.
-- ============================================================================

CREATE TABLE IF NOT EXISTS delivery_zones (
    district TEXT PRIMARY KEY,
    delivery_available BOOLEAN NOT NULL,
    same_day BOOLEAN NOT NULL,
    express_available BOOLEAN NOT NULL,
    minimum_notice_hours INTEGER NOT NULL CHECK (minimum_notice_hours >= 0),
    max_daily_orders INTEGER NOT NULL CHECK (max_daily_orders >= 0),
    active_couriers INTEGER NOT NULL CHECK (active_couriers >= 0)
);

COMMENT ON TABLE delivery_zones IS 'District-level delivery coverage and capacity configuration for Kapruka logistics';

-- ============================================================================
-- LOGISTICS: DELIVERY SLOTS
-- Slot-level delivery availability by district.
-- ============================================================================

CREATE TABLE IF NOT EXISTS delivery_slots (
    district TEXT NOT NULL REFERENCES delivery_zones(district)
        ON UPDATE CASCADE ON DELETE CASCADE,
    slot TEXT NOT NULL,
    capacity INTEGER NOT NULL CHECK (capacity >= 0),
    available BOOLEAN NOT NULL,
    PRIMARY KEY (district, slot)
);

CREATE INDEX IF NOT EXISTS idx_delivery_slots_district
ON delivery_slots(district);

CREATE INDEX IF NOT EXISTS idx_delivery_slots_available
ON delivery_slots(available);

COMMENT ON TABLE delivery_slots IS 'Delivery slot capacity and availability by district';

-- ============================================================================
-- LOGISTICS: COURIER PROFILES
-- Courier capacity and assignment metadata by district.
-- ============================================================================

CREATE TABLE IF NOT EXISTS courier_profiles (
    courier_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    district TEXT NOT NULL REFERENCES delivery_zones(district)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    vehicle_type TEXT NOT NULL,
    availability BOOLEAN NOT NULL,
    max_deliveries_per_day INTEGER NOT NULL CHECK (max_deliveries_per_day >= 0),
    rating REAL NOT NULL CHECK (rating >= 0 AND rating <= 5)
);

CREATE INDEX IF NOT EXISTS idx_courier_profiles_district
ON courier_profiles(district);

CREATE INDEX IF NOT EXISTS idx_courier_profiles_availability
ON courier_profiles(availability);

CREATE INDEX IF NOT EXISTS idx_courier_profiles_vehicle_type
ON courier_profiles(vehicle_type);

COMMENT ON TABLE courier_profiles IS 'Courier profiles used for delivery planning and capacity reasoning';

-- ============================================================================
-- LOGISTICS: PRODUCT DELIVERY RULES
-- Product-level delivery constraints sourced from structured JSON data.
-- ============================================================================

CREATE TABLE IF NOT EXISTS product_delivery_rules (
    product_type TEXT PRIMARY KEY,
    fragile BOOLEAN NOT NULL,
    temperature_control_required BOOLEAN NOT NULL,
    same_day_allowed BOOLEAN NOT NULL,
    minimum_notice_hours INTEGER NOT NULL CHECK (minimum_notice_hours >= 0),
    max_delivery_distance_km INTEGER NOT NULL CHECK (max_delivery_distance_km >= 0)
);

COMMENT ON TABLE product_delivery_rules IS 'Product delivery constraints by Kapruka product type';

-- ============================================================================
-- LOGISTICS: DELIVERY HISTORY
-- Historical delivery outcomes for district/product-level performance reasoning.
-- ============================================================================

CREATE TABLE IF NOT EXISTS delivery_history (
    order_id TEXT PRIMARY KEY,
    district TEXT NOT NULL REFERENCES delivery_zones(district)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    product_type TEXT NOT NULL REFERENCES product_delivery_rules(product_type)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    delivery_time_minutes INTEGER NOT NULL CHECK (delivery_time_minutes >= 0),
    status TEXT NOT NULL CHECK (status IN ('delivered', 'delayed', 'failed', 'cancelled')),
    customer_rating REAL NOT NULL CHECK (customer_rating >= 0 AND customer_rating <= 5)
);

CREATE INDEX IF NOT EXISTS idx_delivery_history_district
ON delivery_history(district);

CREATE INDEX IF NOT EXISTS idx_delivery_history_product_type
ON delivery_history(product_type);

CREATE INDEX IF NOT EXISTS idx_delivery_history_status
ON delivery_history(status);

COMMENT ON TABLE delivery_history IS 'Historical delivery outcomes used for logistics performance analysis';

-- ============================================================================
-- FOREIGN KEY RELATIONSHIPS
-- Canonical user-owned memory tables reference users.user_id.
-- mem_procedures is intentionally excluded because it is shared system memory.
-- ============================================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'fk_st_turns_user_id__users'
    ) THEN
        ALTER TABLE st_turns
        ADD CONSTRAINT fk_st_turns_user_id__users
        FOREIGN KEY (user_id)
        REFERENCES users(user_id)
        ON UPDATE CASCADE
        ON DELETE CASCADE;
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'fk_mem_facts_user_id__users'
    ) THEN
        ALTER TABLE mem_facts
        ADD CONSTRAINT fk_mem_facts_user_id__users
        FOREIGN KEY (user_id)
        REFERENCES users(user_id)
        ON UPDATE CASCADE
        ON DELETE CASCADE;
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'fk_mem_episodes_user_id__users'
    ) THEN
        ALTER TABLE mem_episodes
        ADD CONSTRAINT fk_mem_episodes_user_id__users
        FOREIGN KEY (user_id)
        REFERENCES users(user_id)
        ON UPDATE CASCADE
        ON DELETE CASCADE;
    END IF;
END $$;

-- ============================================================================
-- NOTE: PRODUCT CATALOG STORAGE
-- ============================================================================
-- Kapruka product metadata should be crawled into catalog.json.
-- Each product should then be embedded and stored in Qdrant.
-- Qdrant acts as the RAG knowledge base for semantic product retrieval.
-- Supabase is used here for user CRM, logistics reference data, and cognitive memory.
-- ============================================================================

-- ============================================================================
-- ROW LEVEL SECURITY (RLS)
-- Enable RLS for memory tables and users table.
-- Policies use app.user_id so the backend can set the active user context.
-- ============================================================================

ALTER TABLE st_turns ENABLE ROW LEVEL SECURITY;
ALTER TABLE mem_facts ENABLE ROW LEVEL SECURITY;
ALTER TABLE mem_episodes ENABLE ROW LEVEL SECURITY;
ALTER TABLE users ENABLE ROW LEVEL SECURITY;

-- Drop existing policies for idempotent re-runs.
DROP POLICY IF EXISTS "Users can view their own short term turns" ON st_turns;
DROP POLICY IF EXISTS "Users can manage their own short term turns" ON st_turns;
DROP POLICY IF EXISTS "Users can view their own facts" ON mem_facts;
DROP POLICY IF EXISTS "Users can manage their own facts" ON mem_facts;
DROP POLICY IF EXISTS "Users can view their own episodes" ON mem_episodes;
DROP POLICY IF EXISTS "Users can manage their own episodes" ON mem_episodes;
DROP POLICY IF EXISTS "Users can view their own profile" ON users;
DROP POLICY IF EXISTS "Users can manage their own profile" ON users;

CREATE POLICY "Users can view their own short term turns"
    ON st_turns FOR SELECT
    USING (user_id = current_setting('app.user_id', TRUE));

CREATE POLICY "Users can manage their own short term turns"
    ON st_turns FOR ALL
    USING (user_id = current_setting('app.user_id', TRUE));

CREATE POLICY "Users can view their own facts"
    ON mem_facts FOR SELECT
    USING (user_id = current_setting('app.user_id', TRUE));

CREATE POLICY "Users can manage their own facts"
    ON mem_facts FOR ALL
    USING (user_id = current_setting('app.user_id', TRUE));

CREATE POLICY "Users can view their own episodes"
    ON mem_episodes FOR SELECT
    USING (user_id = current_setting('app.user_id', TRUE));

CREATE POLICY "Users can manage their own episodes"
    ON mem_episodes FOR ALL
    USING (user_id = current_setting('app.user_id', TRUE));

CREATE POLICY "Users can view their own profile"
    ON users FOR SELECT
    USING (user_id = current_setting('app.user_id', TRUE));

CREATE POLICY "Users can manage their own profile"
    ON users FOR ALL
    USING (user_id = current_setting('app.user_id', TRUE));

-- mem_procedures is shared system memory, so RLS is not enabled by default.
-- If exposed to users directly, add read-only policies or backend-only access.

-- ============================================================================
-- VIEWS FOR BASIC ANALYTICS
-- ============================================================================

CREATE OR REPLACE VIEW v_active_facts AS
SELECT
    user_id,
    COUNT(*) AS total_facts,
    AVG(score) AS avg_score,
    COUNT(*) FILTER (WHERE pin = TRUE) AS pinned_facts,
    MAX(last_used_at) AS last_fact_used_at
FROM mem_facts
WHERE deleted = FALSE
    AND (ttl_at IS NULL OR ttl_at > NOW())
GROUP BY user_id;

CREATE OR REPLACE VIEW v_episode_stats AS
SELECT
    user_id,
    COUNT(*) AS total_episodes,
    SUM(turn_count) AS total_turns,
    AVG(turn_count) AS avg_turns_per_episode,
    MAX(created_at) AS last_episode_at
FROM mem_episodes
GROUP BY user_id;

CREATE OR REPLACE VIEW v_user_memory_summary AS
SELECT
    u.user_id,
    u.full_name,
    u.email,
    u.phone,
    u.district,
    COALESCE(f.total_facts, 0) AS total_facts,
    COALESCE(e.total_episodes, 0) AS total_episodes,
    f.last_fact_used_at,
    e.last_episode_at
FROM users u
LEFT JOIN v_active_facts f ON u.user_id = f.user_id
LEFT JOIN v_episode_stats e ON u.user_id = e.user_id
WHERE u.active = TRUE;

CREATE OR REPLACE VIEW v_delivery_history_stats AS
SELECT
    district,
    product_type,
    COUNT(*) AS total_orders,
    AVG(delivery_time_minutes)::REAL AS avg_delivery_time_minutes,
    AVG(customer_rating)::REAL AS avg_customer_rating,
    COUNT(*) FILTER (WHERE status = 'delivered') AS delivered_count,
    COUNT(*) FILTER (WHERE status = 'delayed') AS delayed_count,
    COUNT(*) FILTER (WHERE status = 'failed') AS failed_count,
    COUNT(*) FILTER (WHERE status = 'cancelled') AS cancelled_count
FROM delivery_history
GROUP BY district, product_type;

COMMENT ON VIEW v_active_facts IS 'Summary of active semantic facts per Kapruka user';
COMMENT ON VIEW v_episode_stats IS 'Summary of episodic memory per Kapruka user';
COMMENT ON VIEW v_user_memory_summary IS 'Combined CRM and memory summary for Kapruka users';
COMMENT ON VIEW v_delivery_history_stats IS 'Aggregated delivery performance by district and product type';

-- ============================================================================
-- COMPLETION
-- ============================================================================

DO $$
BEGIN
    RAISE NOTICE '✅ Kapruka Supabase schema created successfully!';
    RAISE NOTICE '📊 CRM/logistics tables created: users, delivery_zones, delivery_slots, courier_profiles, product_delivery_rules, delivery_history';
    RAISE NOTICE '🧠 Memory tables created: st_turns, mem_facts, mem_episodes, mem_procedures';
    RAISE NOTICE '🔍 pgvector indexes created with IVFFlat cosine similarity';
    RAISE NOTICE '📝 Embedding model: text-embedding-3-small (1536 dims)';
    RAISE NOTICE '📦 Product catalog storage: Qdrant RAG knowledge base, not Supabase';
    RAISE NOTICE '🔒 RLS enabled for user-owned memory and CRM user profile data';
    RAISE NOTICE '🚚 Structured logistics reference data is expected from JSON-backed seed assets';
    RAISE NOTICE '🎯 Ready for Kapruka Gift-Concierge Agent development!';
END $$;
