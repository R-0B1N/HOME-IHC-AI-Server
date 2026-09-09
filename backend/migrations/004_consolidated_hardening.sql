-- ==============================================================================
-- Migration 004: Consolidated Database Performance, Vector HNSW & Security Hardening
-- ==============================================================================

-- 1. Ensure pgvector extension is installed
CREATE EXTENSION IF NOT EXISTS vector;

-- 2. HNSW Vector Indexes on Properties (Cosine Distance)
CREATE INDEX IF NOT EXISTS idx_properties_hnsw_overview 
ON properties USING hnsw (embedding_overview vector_cosine_ops) 
WITH (m = 16, ef_construction = 64);

CREATE INDEX IF NOT EXISTS idx_properties_hnsw_features 
ON properties USING hnsw (embedding_features vector_cosine_ops) 
WITH (m = 16, ef_construction = 64);

CREATE INDEX IF NOT EXISTS idx_properties_hnsw_specs 
ON properties USING hnsw (embedding_specs vector_cosine_ops) 
WITH (m = 16, ef_construction = 64);

CREATE INDEX IF NOT EXISTS idx_properties_hnsw_location 
ON properties USING hnsw (embedding_location vector_cosine_ops) 
WITH (m = 16, ef_construction = 64);

CREATE INDEX IF NOT EXISTS idx_properties_hnsw_suitability 
ON properties USING hnsw (embedding_suitability vector_cosine_ops) 
WITH (m = 16, ef_construction = 64);

-- 3. GIN Index on Property Category Array
CREATE INDEX IF NOT EXISTS idx_properties_category_gin 
ON properties USING GIN (property_category);

-- 4. Relational B-Tree Query Optimization Indexes
CREATE INDEX IF NOT EXISTS idx_customers_last_interaction 
ON customers (last_interaction DESC);

CREATE INDEX IF NOT EXISTS idx_customers_inbox_id 
ON customers (((metadata_json->>'inbox_id')::int));

CREATE INDEX IF NOT EXISTS idx_properties_listing_status 
ON properties (listing_status);

CREATE INDEX IF NOT EXISTS idx_properties_city_state 
ON properties (city, state);

CREATE INDEX IF NOT EXISTS idx_properties_asking_price 
ON properties (asking_price_myr);

CREATE INDEX IF NOT EXISTS idx_leads_customer_id 
ON leads (customer_id);

CREATE INDEX IF NOT EXISTS idx_leads_temp_status 
ON leads (lead_temperature, lead_status);
