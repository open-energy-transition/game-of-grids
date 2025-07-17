#!/usr/bin/env python3
"""
Database schema creation script for Osmose processing pipeline
"""

from utils import get_db_connection, close_db_connection, setup_logging

logger = setup_logging()

def create_tables():
    """Create all required database tables"""
    conn = get_db_connection()
    
    try:
        with conn.cursor() as cur:
            # Create import_batches table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS import_batches (
                    batch_id SERIAL PRIMARY KEY,
                    imported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    imported_by VARCHAR(100) NOT NULL,
                    country_code VARCHAR(5) NOT NULL,
                    source_file VARCHAR(255),
                    patches_count INTEGER DEFAULT 0,
                    errors_count INTEGER DEFAULT 0,
                    new_patches INTEGER DEFAULT 0,
                    duplicate_patches INTEGER DEFAULT 0,
                    failed_patches INTEGER DEFAULT 0,
                    status VARCHAR(20) DEFAULT 'completed'
                );
            """)
            logger.info("Created import_batches table")
            
            # Create osmose_errors table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS osmose_errors (
                    error_id VARCHAR(50) PRIMARY KEY,
                    patch_id VARCHAR(100),
                    location GEOMETRY(Point, 4326) NOT NULL,
                    item INTEGER,
                    class INTEGER,
                    title TEXT,
                    subtitle TEXT,
                    username VARCHAR(100),
                    error_timestamp TIMESTAMP,
                    osmose_url TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            logger.info("Created osmose_errors table")
            
            # Create osmose_patches table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS osmose_patches (
                    patch_id VARCHAR(100) PRIMARY KEY,
                    geometry GEOMETRY(Polygon, 4326) NOT NULL,
                    country_code VARCHAR(5) NOT NULL,
                    country_name VARCHAR(100),
                    osmose_ids TEXT[] NOT NULL,
                    area_km2 DECIMAL(10,3) NOT NULL,
                    perimeter_km DECIMAL(10,3) NOT NULL,
                    error_count INTEGER NOT NULL DEFAULT 0,
                    source_file VARCHAR(255),
                    import_batch INTEGER REFERENCES import_batches(batch_id),
                    priority INTEGER DEFAULT 5,
                    difficulty VARCHAR(10) DEFAULT 'medium',
                    status VARCHAR(20) DEFAULT 'open',
                    assigned_to VARCHAR(100),
                    completed_at TIMESTAMP,
                    metadata JSONB,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            logger.info("Created osmose_patches table")
            
            # Create indexes for better performance
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_osmose_errors_location 
                ON osmose_errors USING GIST (location);
            """)
            
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_osmose_errors_patch_id 
                ON osmose_errors (patch_id);
            """)
            
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_osmose_patches_geometry 
                ON osmose_patches USING GIST (geometry);
            """)
            
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_osmose_patches_country 
                ON osmose_patches (country_code);
            """)
            
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_osmose_patches_priority 
                ON osmose_patches (priority DESC);
            """)
            
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_osmose_patches_status 
                ON osmose_patches (status);
            """)
            
            logger.info("Created database indexes")
            
            # Create foreign key constraint
            cur.execute("""
                ALTER TABLE osmose_errors 
                ADD CONSTRAINT fk_osmose_errors_patch_id 
                FOREIGN KEY (patch_id) REFERENCES osmose_patches(patch_id)
                ON DELETE SET NULL;
            """)
            logger.info("Added foreign key constraints")
            
            conn.commit()
            logger.info("Database schema created successfully")
            
    except Exception as e:
        logger.error(f"Failed to create database schema: {e}")
        conn.rollback()
        raise
    finally:
        close_db_connection(conn)

def drop_tables():
    """Drop all tables (for testing/reset purposes)"""
    conn = get_db_connection()
    
    try:
        with conn.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS osmose_errors CASCADE;")
            cur.execute("DROP TABLE IF EXISTS osmose_patches CASCADE;")
            cur.execute("DROP TABLE IF EXISTS import_batches CASCADE;")
            conn.commit()
            logger.info("All tables dropped successfully")
            
    except Exception as e:
        logger.error(f"Failed to drop tables: {e}")
        conn.rollback()
        raise
    finally:
        close_db_connection(conn)

def main():
    """Main function"""
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == '--drop':
        logger.warning("Dropping all tables...")
        drop_tables()
    
    create_tables()

if __name__ == "__main__":
    main()