-- User Roles Table
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    phone_number VARCHAR(50) UNIQUE NOT NULL,
    role VARCHAR(50) NOT NULL DEFAULT 'customer',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Seed some example users
INSERT INTO users (name, phone_number, role)
VALUES 
    ('Admin User', '+601163044931', 'admin'),
    ('Chinyee', '+601110044931', 'employee'),
    ('Admin Nick', '+60126761818', 'admin')
ON CONFLICT (phone_number) DO UPDATE SET role = EXCLUDED.role;
