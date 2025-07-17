#!/usr/bin/env python3
"""
Osmose Issues Loader - Fetches Osmose errors from API and stores in database
"""

import requests
import time
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from psycopg2.extras import RealDictCursor

from config import OSMOSE_CONFIG
from utils import get_db_connection, close_db_connection, setup_logging

logger = setup_logging()

class OsmoseIssuesLoader:
    """Loads Osmose issues from API and stores them in database"""
    
    def __init__(self):
        self.conn = None
        self.batch_id = None
        
    def connect_db(self):
        """Connect to database"""
        self.conn = get_db_connection()
        logger.info("Connected to database")
            
    def close_db(self):
        """Close database connection"""
        if self.conn:
            close_db_connection(self.conn)
            
    def fetch_osmose_errors(self, limit: Optional[int] = None) -> List[Dict]:
        """Fetch Osmose errors from API"""
        errors = []
        
        params = {
            'country': OSMOSE_CONFIG['COUNTRY_NAME'],
            'item': OSMOSE_CONFIG['ITEM'],
            'class': OSMOSE_CONFIG['CLASS'],
            'status': 'open',
            'limit': OSMOSE_CONFIG['FETCH_LIMIT']
        }
        
        url = f"{OSMOSE_CONFIG['API_BASE']}/issues"
        page = 0
        total_fetched = 0
        
        logger.info(f"Fetching Osmose errors for {OSMOSE_CONFIG['COUNTRY_NAME']}")
        
        while True:
            try:
                params['offset'] = page * params['limit']
                
                response = requests.get(
                    url, 
                    params=params, 
                    timeout=OSMOSE_CONFIG['REQUEST_TIMEOUT']
                )
                response.raise_for_status()
                
                data = response.json()
                issues = data.get('issues', [])
                
                if not issues:
                    break
                    
                errors.extend(issues)
                total_fetched += len(issues)
                
                logger.info(f"Fetched {len(issues)} errors (total: {total_fetched})")
                
                if limit and total_fetched >= limit:
                    errors = errors[:limit]
                    break
                    
                if len(issues) < params['limit']:
                    break
                    
                page += 1
                time.sleep(OSMOSE_CONFIG['REQUEST_DELAY'])
                
            except requests.exceptions.RequestException as e:
                logger.error(f"API request failed: {e}")
                break
                
        logger.info(f"Total errors fetched: {len(errors)}")
        return errors
        
    def create_import_batch(self) -> str:
        """Create a new import batch record"""
        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO import_batches (
                    imported_by,
                    country_code,
                    source_file
                ) VALUES (
                    %s, %s, %s
                ) RETURNING batch_id
            """, (
                'osmose_api_loader',
                OSMOSE_CONFIG['COUNTRY_CODE'],
                f'osmose_api_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
            ))
            self.batch_id = cur.fetchone()[0]
            self.conn.commit()
            
        logger.info(f"Created import batch: {self.batch_id}")
        return self.batch_id
        
    def insert_errors(self, errors: List[Dict]) -> Tuple[int, int, int]:
        """Insert errors into database"""
        success_count = 0
        duplicate_count = 0
        error_count = 0
        
        with self.conn.cursor() as cur:
            for error in errors:
                try:
                    # Check for valid coordinates
                    lat = error.get('lat')
                    lon = error.get('lon')
                    error_id = error.get('id')
                    
                    if not (lat and lon and error_id):
                        error_count += 1
                        logger.warning(f"Invalid error data: {error_id}")
                        continue
                    
                    # Check for duplicates
                    cur.execute("""
                        SELECT COUNT(*) FROM osmose_errors 
                        WHERE error_id = %s
                    """, (str(error_id),))
                    
                    if cur.fetchone()[0] > 0:
                        duplicate_count += 1
                        continue
                        
                    # Insert error
                    cur.execute("""
                        INSERT INTO osmose_errors (
                            error_id,
                            location,
                            item,
                            class,
                            title,
                            subtitle,
                            username,
                            error_timestamp,
                            osmose_url
                        ) VALUES (
                            %s,
                            ST_SetSRID(ST_MakePoint(%s, %s), 4326),
                            %s, %s, %s, %s, %s, %s, %s
                        )
                    """, (
                        str(error_id),
                        lon, lat,
                        error.get('item', OSMOSE_CONFIG['ITEM']),
                        error.get('class', OSMOSE_CONFIG['CLASS']),
                        error.get('title', 'Forest area without leaf_type'),
                        error.get('subtitle', ''),
                        error.get('username'),
                        datetime.fromisoformat(error['date'].replace('Z', '+00:00')) 
                            if error.get('date') else None,
                        f"https://osmose.openstreetmap.fr/en/error/{error_id}"
                    ))
                    
                    success_count += 1
                    
                    if success_count % 100 == 0:
                        self.conn.commit()
                        logger.info(f"Inserted {success_count} errors...")
                    
                except Exception as e:
                    error_count += 1
                    logger.error(f"Failed to insert error {error.get('id', 'unknown')}: {e}")
                    continue
                    
            # Final commit
            self.conn.commit()
                    
        # Update batch statistics
        with self.conn.cursor() as cur:
            cur.execute("""
                UPDATE import_batches
                SET errors_count = %s,
                    new_patches = %s,
                    duplicate_patches = %s,
                    failed_patches = %s
                WHERE batch_id = %s
            """, (
                success_count,
                success_count,
                duplicate_count,
                error_count,
                self.batch_id
            ))
            self.conn.commit()
            
        return success_count, duplicate_count, error_count
        
    def get_summary_stats(self) -> Dict:
        """Get summary statistics of loaded data"""
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Total errors
            cur.execute("SELECT COUNT(*) as total_errors FROM osmose_errors")
            total_errors = cur.fetchone()['total_errors']
            
            # Errors by batch
            cur.execute("""
                SELECT batch_id, COUNT(*) as error_count 
                FROM osmose_errors e
                WHERE error_id IN (
                    SELECT UNNEST(osmose_ids) 
                    FROM osmose_patches 
                    WHERE import_batch = %s
                )
                GROUP BY batch_id
            """, (self.batch_id,))
            
            batch_stats = cur.fetchall()
            
            # Recent batches
            cur.execute("""
                SELECT batch_id, imported_at, errors_count, source_file
                FROM import_batches 
                ORDER BY imported_at DESC 
                LIMIT 5
            """)
            recent_batches = cur.fetchall()
            
            return {
                'total_errors': total_errors,
                'batch_stats': batch_stats,
                'recent_batches': recent_batches
            }
            
    def run(self, limit: Optional[int] = None):
        """Run the complete import process"""
        try:
            self.connect_db()
            self.create_import_batch()
            
            # Fetch errors from API
            errors = self.fetch_osmose_errors(limit)
            
            if not errors:
                logger.warning("No errors fetched from API")
                return
                
            # Insert errors into database
            success, duplicates, failures = self.insert_errors(errors)
            
            # Print summary
            logger.info(f"\nImport Summary:")
            logger.info(f"  Total errors fetched: {len(errors)}")
            logger.info(f"  Successfully imported: {success}")
            logger.info(f"  Duplicates skipped: {duplicates}")
            logger.info(f"  Failed: {failures}")
            logger.info(f"  Import batch ID: {self.batch_id}")
            
            # Get and display stats
            stats = self.get_summary_stats()
            logger.info(f"\nDatabase Stats:")
            logger.info(f"  Total errors in database: {stats['total_errors']}")
            
            return self.batch_id
            
        except Exception as e:
            logger.error(f"Import failed: {e}")
            raise
        finally:
            self.close_db()


def main():
    """Main function"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Load Osmose issues from API')
    parser.add_argument('--limit', type=int, help='Limit number of errors to fetch')
    parser.add_argument('--test', action='store_true', help='Run with small limit for testing')
    
    args = parser.parse_args()
    
    limit = args.limit
    if args.test:
        limit = 100
        
    loader = OsmoseIssuesLoader()
    batch_id = loader.run(limit=limit)
    
    print(f"\nCompleted import with batch ID: {batch_id}")


if __name__ == "__main__":
    main()