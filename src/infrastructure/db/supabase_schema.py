"""
Dynamic Supabase schema generator - reads dimensions from config.

This ensures the database schema always matches config.EMBEDDING_DIM
without any hardcoded values in SQL files.
"""


from infrastructure.config import EMBEDDING_DIM, EMBEDDING_MODEL


def generate_supabase_schema() -> str:
    """
    Generate Supabase schema DDL dynamically from config.

    Returns:
        SQL DDL string with vector dimensions from config.EMBEDDING_DIM.
    """

    return f"""-- ============================================================================
-- Supabase Schema: Kapruka Gift-Concierge Agent
-- Memory System + Minimal CRM
-- PostgreSQL 15+ with pgvector extension
-- ============================================================================
--
-- ⚠️ DYNAMICALLY GENERATED FROM CONFIG
-- Embedding Model: {EMBEDDING_MODEL}
-- Vector Dimensions: {EMBEDDING_DIM}
--
-- Product catalog RAG documents are stored in Qdrant, not Supabase.
-- Supabase stores agent memory and minimal user CRM data.
--
-- ============================================================================

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================================
-- SHORT-TERM MEMORY
-- Stores raw conversation turns for the active session.
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

COMMENT ON TABLE st_turns IS 'Short-term conversation memory for the Kapruka Gift-Concierge Agent';

-- ============================================================================
-- LONG-TERM SEMANTIC MEMORY
-- Stores extracted user facts such as preferences, allergies, budget, district,
-- occasion preferences, disliked items, and gift interests.
-- ============================================================================

CREATE TABLE IF NOT EXISTS mem_facts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL,
    text TEXT NOT NULL,
    embedding vector({EMBEDDING_DIM}),
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

CREATE INDEX IF NOT EXISTS idx_mem_facts_embedding
ON mem_facts USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);

CREATE OR REPLACE FUNCTION search_mem_facts(
    query_embedding vector({EMBEDDING_DIM}),
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

-- ============================================================================
-- LONG-TERM EPISODIC MEMORY
-- Stores summarized past conversations or gift-planning sessions.
-- ============================================================================

CREATE TABLE IF NOT EXISTS mem_episodes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    summary TEXT NOT NULL,
    summary_embedding vector({EMBEDDING_DIM}),
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
ON mem_episodes USING ivfflat (summary_embedding vector_cosine_ops)
WITH (lists = 100);

CREATE OR REPLACE FUNCTION search_mem_episodes(
    query_embedding vector({EMBEDDING_DIM}),
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

-- ============================================================================
-- PROCEDURAL MEMORY
-- Stores reusable agent workflows such as preference extraction, product search,
-- logistics validation, and reflection/revision.
-- ============================================================================

CREATE TABLE IF NOT EXISTS mem_procedures (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL,
    context_when TEXT,
    steps JSONB NOT NULL,
    conditions JSONB,
    examples JSONB,
    embedding vector({EMBEDDING_DIM}),
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
ON mem_procedures USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 50);

CREATE OR REPLACE FUNCTION search_mem_procedures(
    query_embedding vector({EMBEDDING_DIM}),
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

COMMENT ON TABLE mem_procedures IS 'Procedural memory for Kapruka agent workflows';

-- ============================================================================
-- CRM: USERS
-- Minimal CRM table for Kapruka customers.
-- Detailed preferences are stored as semantic facts in mem_facts.
-- Product catalog data is stored in Qdrant.
-- ============================================================================

CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    external_user_id TEXT UNIQUE,
    full_name TEXT,
    phone TEXT,
    email TEXT,
    district TEXT,
    notes TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_users_external_user_id
ON users(external_user_id);

CREATE INDEX IF NOT EXISTS idx_users_phone
ON users(phone);

CREATE INDEX IF NOT EXISTS idx_users_email
ON users(email);

CREATE INDEX IF NOT EXISTS idx_users_district
ON users(district);

COMMENT ON TABLE users IS 'Minimal Kapruka CRM user profiles. Preferences live in mem_facts.';

-- ============================================================================
-- ROW LEVEL SECURITY
-- ============================================================================

ALTER TABLE st_turns ENABLE ROW LEVEL SECURITY;
ALTER TABLE mem_facts ENABLE ROW LEVEL SECURITY;
ALTER TABLE mem_episodes ENABLE ROW LEVEL SECURITY;
ALTER TABLE users ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users can view their own turns" ON st_turns;
DROP POLICY IF EXISTS "Users can manage their own turns" ON st_turns;
DROP POLICY IF EXISTS "Users can view their own facts" ON mem_facts;
DROP POLICY IF EXISTS "Users can manage their own facts" ON mem_facts;
DROP POLICY IF EXISTS "Users can view their own episodes" ON mem_episodes;
DROP POLICY IF EXISTS "Users can manage their own episodes" ON mem_episodes;
DROP POLICY IF EXISTS "Users can view their own profile" ON users;
DROP POLICY IF EXISTS "Users can manage their own profile" ON users;

CREATE POLICY "Users can view their own turns"
    ON st_turns FOR SELECT
    USING (user_id = current_setting('app.user_id', TRUE));

CREATE POLICY "Users can manage their own turns"
    ON st_turns FOR ALL
    USING (user_id = current_setting('app.user_id', TRUE))
    WITH CHECK (user_id = current_setting('app.user_id', TRUE));

CREATE POLICY "Users can view their own facts"
    ON mem_facts FOR SELECT
    USING (user_id = current_setting('app.user_id', TRUE));

CREATE POLICY "Users can manage their own facts"
    ON mem_facts FOR ALL
    USING (user_id = current_setting('app.user_id', TRUE))
    WITH CHECK (user_id = current_setting('app.user_id', TRUE));

CREATE POLICY "Users can view their own episodes"
    ON mem_episodes FOR SELECT
    USING (user_id = current_setting('app.user_id', TRUE));

CREATE POLICY "Users can manage their own episodes"
    ON mem_episodes FOR ALL
    USING (user_id = current_setting('app.user_id', TRUE))
    WITH CHECK (user_id = current_setting('app.user_id', TRUE));

CREATE POLICY "Users can view their own profile"
    ON users FOR SELECT
    USING (user_id = current_setting('app.user_id', TRUE));

CREATE POLICY "Users can manage their own profile"
    ON users FOR ALL
    USING (user_id = current_setting('app.user_id', TRUE))
    WITH CHECK (user_id = current_setting('app.user_id', TRUE));

-- ============================================================================
-- ANALYTICS VIEWS
-- ============================================================================

CREATE OR REPLACE VIEW v_active_facts AS
SELECT
    user_id,
    COUNT(*) AS total_facts,
    AVG(score) AS avg_score,
    COUNT(*) FILTER (WHERE pin = TRUE) AS pinned_facts
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
    u.phone,
    u.email,
    u.district,
    COUNT(f.id) FILTER (
        WHERE f.deleted = FALSE
        AND (f.ttl_at IS NULL OR f.ttl_at > NOW())
    ) AS active_fact_count,
    COUNT(e.id) AS episode_count
FROM users u
LEFT JOIN mem_facts f ON f.user_id = u.user_id
LEFT JOIN mem_episodes e ON e.user_id = u.user_id
GROUP BY u.user_id, u.full_name, u.phone, u.email, u.district;

-- ============================================================================
-- DOCUMENTATION
-- ============================================================================

COMMENT ON TABLE mem_facts IS 'Long-term semantic memory facts with pgvector embeddings';
COMMENT ON TABLE mem_episodes IS 'Long-term episodic memory with pgvector summaries';
COMMENT ON TABLE users IS 'Kapruka Gift-Concierge CRM users';

COMMENT ON FUNCTION search_mem_facts IS 'Semantic search over memory facts using cosine similarity';
COMMENT ON FUNCTION search_mem_episodes IS 'Semantic search over episode summaries using cosine similarity';
COMMENT ON FUNCTION search_mem_procedures IS 'Semantic search over procedural memory using cosine similarity';

-- ============================================================================
-- COMPLETION
-- ============================================================================

DO $$
BEGIN
    RAISE NOTICE '✅ Kapruka Supabase schema created successfully!';
    RAISE NOTICE '📊 Tables created: st_turns, mem_facts, mem_episodes, mem_procedures, users';
    RAISE NOTICE '🔍 pgvector indexes created with IVFFlat cosine similarity';
    RAISE NOTICE '📝 Model: {EMBEDDING_MODEL} ({EMBEDDING_DIM} dims)';
    RAISE NOTICE '🔒 RLS enabled for memory tables and users table';
    RAISE NOTICE '💾 CRM: minimal users table only';
    RAISE NOTICE '🧠 Memory types: Short-term, Semantic, Episodic, Procedural';
    RAISE NOTICE '🎁 Product catalog RAG store: Qdrant';
END $$;
"""
