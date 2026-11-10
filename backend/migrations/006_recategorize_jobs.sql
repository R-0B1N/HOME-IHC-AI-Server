-- Recategorization jobs and pre-apply snapshots.
-- dry_run does not insert snapshots. apply inserts one row per accepted
-- conversation before it changes customers.metadata_json or Chatwoot labels.

CREATE TABLE IF NOT EXISTS recategorize_jobs (
    batch_id VARCHAR PRIMARY KEY,
    mode VARCHAR NOT NULL DEFAULT 'dry_run',
    status VARCHAR NOT NULL DEFAULT 'queued',
    done INTEGER DEFAULT 0,
    total INTEGER DEFAULT 0,
    output_csv VARCHAR,
    output_xlsx VARCHAR,
    checkpoint_json JSONB DEFAULT '[]',
    accepted_ids JSONB DEFAULT '[]',
    summary_json JSONB DEFAULT '{}',
    error TEXT,
    rate DOUBLE PRECISION DEFAULT 1.0,
    conversation_limit INTEGER,
    conversation_id VARCHAR,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS recategorize_snapshots (
    id SERIAL PRIMARY KEY,
    batch_id VARCHAR NOT NULL,
    conversation_id VARCHAR NOT NULL,
    customer_id VARCHAR,
    previous_metadata JSONB DEFAULT '{}',
    previous_labels JSONB DEFAULT '[]',
    proposed_category VARCHAR,
    proposed_temperature VARCHAR,
    transcript_hash VARCHAR,
    applied BOOLEAN DEFAULT FALSE,
    rolled_back BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_recategorize_snapshot_batch_conv UNIQUE (batch_id, conversation_id)
);

CREATE INDEX IF NOT EXISTS idx_recategorize_snapshots_batch
    ON recategorize_snapshots (batch_id);
