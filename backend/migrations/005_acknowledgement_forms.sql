-- ==============================================================================
-- Migration 005: Viewing Acknowledgement Forms Table & State Tracking
-- ==============================================================================

CREATE TABLE IF NOT EXISTS acknowledgement_forms (
    id SERIAL PRIMARY KEY,
    form_no VARCHAR(64) UNIQUE NOT NULL,
    customer_id VARCHAR(64) REFERENCES customers(id) ON DELETE SET NULL,
    property_id UUID REFERENCES properties(id) ON DELETE SET NULL,
    viewing_date TIMESTAMP WITH TIME ZONE,
    status VARCHAR(32) NOT NULL DEFAULT 'PENDING_SIGNATURE',
    file_path TEXT,
    document_hash VARCHAR(128),
    metadata_json JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for rapid lookup and foreign key joins
CREATE INDEX IF NOT EXISTS idx_acknowledgement_forms_form_no ON acknowledgement_forms (form_no);
CREATE INDEX IF NOT EXISTS idx_acknowledgement_forms_customer_id ON acknowledgement_forms (customer_id);
CREATE INDEX IF NOT EXISTS idx_acknowledgement_forms_property_id ON acknowledgement_forms (property_id);
CREATE INDEX IF NOT EXISTS idx_acknowledgement_forms_status ON acknowledgement_forms (status);
CREATE INDEX IF NOT EXISTS idx_acknowledgement_forms_viewing_date ON acknowledgement_forms (viewing_date);
