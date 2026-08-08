import uuid
import sys
sys.path.append('.')
from sqlalchemy import create_engine, text
from app.db.models import DATABASE_URL, Base

def migrate():
    engine = create_engine(DATABASE_URL)
    
    with engine.connect() as conn:
        try:
            # Check if pgvector is enabled
            # conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
            
            result = conn.execute(text("SELECT data_type FROM information_schema.columns WHERE table_name = 'properties' AND column_name = 'id';"))
            id_type = result.scalar()
            
            if id_type == 'integer':
                print("Migrating integer IDs to UUIDs...")
                # Rename old table and its indexes
                conn.execute(text("ALTER TABLE properties RENAME TO properties_old;"))
                conn.execute(text("ALTER INDEX IF EXISTS properties_pkey RENAME TO properties_old_pkey;"))
                conn.execute(text("ALTER INDEX IF EXISTS ix_properties_id RENAME TO ix_properties_old_id;"))
                conn.execute(text("ALTER INDEX IF EXISTS ix_properties_title RENAME TO ix_properties_old_title;"))
                
                res_trans = conn.execute(text("SELECT data_type FROM information_schema.columns WHERE table_name = 'transactions' AND column_name = 'property_id';"))
                trans_prop_type = res_trans.scalar()
                if trans_prop_type == 'integer':
                    conn.execute(text("ALTER TABLE transactions RENAME TO transactions_old;"))
                    conn.execute(text("ALTER INDEX IF EXISTS transactions_pkey RENAME TO transactions_old_pkey;"))
                    conn.execute(text("ALTER INDEX IF EXISTS ix_transactions_id RENAME TO ix_transactions_old_id;"))
                    conn.execute(text("ALTER TABLE transactions_old DROP CONSTRAINT IF EXISTS transactions_property_id_fkey;"))
                
                # Create new tables
                Base.metadata.create_all(bind=conn)
                
                
                # Transfer properties
                print("Transferring properties data...")
                # For postgres, gen_random_uuid() is built-in
                # We create a temporary mapping table to link old integer ID to new UUID
                conn.execute(text("CREATE TEMP TABLE id_mapping (old_id integer, new_id uuid);"))
                
                # Insert properties and record the mapping
                properties_old = conn.execute(text("SELECT * FROM properties_old;")).fetchall()
                for p in properties_old:
                    new_id = str(uuid.uuid4())
                    
                    # Some basic mapping from old to new. If a column is missing in old, we use a default
                    category = p.category if hasattr(p, 'category') else ''
                    prop_type = p.property_type if hasattr(p, 'property_type') else ''
                    
                    # Convert to postgres array literal safely or use parameterized query
                    conn.execute(text("""
                        INSERT INTO properties (
                            id, source_url, title, search_corpus_markdown, listing_status, 
                            property_category, asking_price_myr, state, 
                            city, street_address, land_area_acres
                        ) VALUES (
                            :id, :source_url, :title, :description, :status, 
                            :category, :price, :state, :city, :address, :acres
                        )
                    """), {
                        "id": new_id,
                        "source_url": "",
                        "title": getattr(p, 'name', ''),
                        "description": getattr(p, 'description', ''),
                        "status": getattr(p, 'status', 'Available'),
                        "category": [category, prop_type] if category or prop_type else [],
                        "price": getattr(p, 'price', 0),
                        "state": getattr(p, 'state', ''),
                        "city": getattr(p, 'city', ''),
                        "address": getattr(p, 'location', ''),
                        "acres": getattr(p, 'acres', 0.0)
                    })
                    
                    conn.execute(text("INSERT INTO id_mapping (old_id, new_id) VALUES (:old, :new)"), 
                                 {"old": getattr(p, 'id'), "new": new_id})

                # Migrate transactions if they existed
                if trans_prop_type == 'integer':
                    print("Transferring transactions data...")
                    transactions_old = conn.execute(text("SELECT * FROM transactions_old;")).fetchall()
                    for t in transactions_old:
                        mapping = conn.execute(text("SELECT new_id FROM id_mapping WHERE old_id = :old"), {"old": getattr(t, 'property_id')}).scalar()
                        
                        conn.execute(text("""
                            INSERT INTO transactions (
                                id, property_id, customer_id, type, amount, status, date
                            ) VALUES (
                                :id, :pid, :cid, :typ, :amt, :stat, :dt
                            )
                        """), {
                            "id": str(uuid.uuid4()),
                            "pid": mapping,
                            "cid": getattr(t, 'customer_id'),
                            "typ": getattr(t, 'type', 'Sale'),
                            "amt": getattr(t, 'amount', 0.0),
                            "stat": getattr(t, 'status', 'Pending'),
                            "dt": getattr(t, 'date')
                        })
                
                print("Data migrated successfully.")
                
            elif id_type == 'character varying' or id_type == 'uuid':
                print("Table 'properties' is already using UUIDs or Strings. No integer migration needed.")
            elif id_type is None:
                print("Table 'properties' does not exist yet. Creating tables...")
                Base.metadata.create_all(bind=engine)
            else:
                print(f"Unknown id type: {id_type}")
                
            
            # --- Migrate Leads to Customers ---
            leads_exists = conn.execute(text("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'leads');")).scalar()
            migrated_exists = conn.execute(text("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'leads_migrated');")).scalar()
            
            if leads_exists and not migrated_exists:
                print("Migrating leads to customers...")
                old_leads = conn.execute(text("SELECT * FROM leads;")).fetchall()
                for lead in old_leads:
                    # Ensure customer exists
                    cust_exists = conn.execute(text("SELECT 1 FROM customers WHERE id = :pid"), {"pid": lead.phone_number}).scalar()
                    if not cust_exists:
                        conn.execute(text("""
                            INSERT INTO customers (
                                id, contact_name, intent_category, last_interaction, metadata_json
                            ) VALUES (
                                :id, :name, :intent, :last_int, :meta
                            )
                        """), {
                            "id": lead.phone_number,
                            "name": lead.contact_name,
                            "intent": getattr(lead, 'intent_category', 'general'),
                            "last_int": getattr(lead, 'last_interaction', None),
                            "meta": getattr(lead, 'metadata_json', None)
                        })
                
                int_col_type = conn.execute(text("SELECT data_type FROM information_schema.columns WHERE table_name = 'interactions' AND column_name = 'lead_id';")).scalar()
                if int_col_type == 'integer':
                    print("Migrating interactions to use customer_id...")
                    conn.execute(text("ALTER TABLE interactions RENAME TO interactions_old_leads;"))
                    # Recreate interactions with customer_id
                    Base.metadata.create_all(bind=engine)
                    
                    old_interactions = conn.execute(text("SELECT * FROM interactions_old_leads;")).fetchall()
                    for old_int in old_interactions:
                        lead_phone = conn.execute(text("SELECT phone_number FROM leads WHERE id = :lid"), {"lid": old_int.lead_id}).scalar()
                        if lead_phone:
                            conn.execute(text("""
                                INSERT INTO interactions (
                                    customer_id, message_in, message_out, timestamp
                                ) VALUES (
                                    :cid, :msg_in, :msg_out, :ts
                                )
                            """), {
                                "cid": lead_phone,
                                "msg_in": old_int.message_in,
                                "msg_out": old_int.message_out,
                                "ts": old_int.timestamp
                            })
                
                # Mark leads as migrated
                conn.execute(text("ALTER TABLE leads RENAME TO leads_migrated;"))
                print("Leads migrated successfully.")
                
            conn.commit()
        except Exception as e:
            print(f"Error during migration: {e}")
            conn.rollback()

if __name__ == "__main__":
    migrate()
