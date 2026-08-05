import json
import os
import psycopg2
from psycopg2.extras import Json

# Read the JSON file
file_path = os.path.join(os.path.dirname(__file__), 'properties_export.json')
with open(file_path, 'r') as f:
    properties = json.load(f)

# Connect to database
# Using the standard connection string that we saw the previous agent use in migrate_properties_to_uuid.py
# Or we can just use psycopg2 to connect to localhost 
conn = psycopg2.connect(
    dbname="crm",
    user="postgres",
    password="password",
    host="localhost",
    port="5432"
)
conn.autocommit = True
cur = conn.cursor()

print(f"Ingesting {len(properties)} properties...")
inserted = 0

for p in properties:
    # Need to handle missing keys and format arrays properly for postgres
    try:
        cur.execute("""
            INSERT INTO properties (
                id, source_url, title, listing_status, property_category, 
                asking_price_myr, currency, monthly_rental_income_myr, implied_yield_pct,
                land_area_sqft, land_area_acres, tenure_type, street_address, area, city, state, country,
                search_corpus_markdown, suitable_industries, agency_name, agent_name, agent_phone, agent_whatsapp_url
            ) VALUES (
                %(id)s, %(source_url)s, %(title)s, %(listing_status)s, %(property_category)s,
                %(asking_price_myr)s, %(currency)s, %(monthly_rental_income_myr)s, %(implied_yield_pct)s,
                %(land_area_sqft)s, %(land_area_acres)s, %(tenure_type)s, %(street_address)s, %(area)s, %(city)s, %(state)s, %(country)s,
                %(search_corpus_markdown)s, %(suitable_industries)s, %(agency_name)s, %(agent_name)s, %(agent_phone)s, %(agent_whatsapp_url)s
            ) ON CONFLICT (id) DO NOTHING;
        """, p)
        inserted += 1
    except Exception as e:
        print(f"Error inserting {p.get('source_url')}: {e}")

print(f"Successfully ingested {inserted} properties.")
cur.close()
conn.close()
