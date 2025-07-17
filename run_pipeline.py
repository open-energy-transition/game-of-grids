#!/usr/bin/env python3
"""
Pipeline Orchestration Script - Runs the complete Osmose processing pipeline
"""

import argparse
import sys
from datetime import datetime

from utils import setup_logging
from osmose_issues_loader import OsmoseIssuesLoader
from patches_creator import PatchesCreator

logger = setup_logging()

def run_full_pipeline(limit: int = None, country_code: str = None):
    """Run the complete pipeline: load issues -> create patches"""
    
    logger.info("="*60)
    logger.info("STARTING OSMOSE PROCESSING PIPELINE")
    logger.info("="*60)
    
    start_time = datetime.now()
    
    try:
        # Step 1: Load Osmose Issues
        logger.info("\n" + "="*40)
        logger.info("STEP 1: LOADING OSMOSE ISSUES")
        logger.info("="*40)
        
        issues_loader = OsmoseIssuesLoader()
        issues_batch_id = issues_loader.run(limit=limit)
        
        if not issues_batch_id:
            logger.error("Failed to load Osmose issues")
            return False
            
        logger.info(f"✓ Successfully loaded issues (Batch ID: {issues_batch_id})")
        
        # Step 2: Create Patches
        logger.info("\n" + "="*40)
        logger.info("STEP 2: CREATING PATCHES")
        logger.info("="*40)
        
        patches_creator = PatchesCreator()
        patches_batch_id = patches_creator.run(country_code=country_code)
        
        if not patches_batch_id:
            logger.error("Failed to create patches")
            return False
            
        logger.info(f"✓ Successfully created patches (Batch ID: {patches_batch_id})")
        
        # Pipeline Summary
        end_time = datetime.now()
        duration = end_time - start_time
        
        logger.info("\n" + "="*60)
        logger.info("PIPELINE COMPLETED SUCCESSFULLY")
        logger.info("="*60)
        logger.info(f"Duration: {duration}")
        logger.info(f"Issues Batch ID: {issues_batch_id}")
        logger.info(f"Patches Batch ID: {patches_batch_id}")
        logger.info("="*60)
        
        return True
        
    except Exception as e:
        logger.error(f"Pipeline failed: {e}")
        return False

def run_issues_only(limit: int = None):
    """Run only the issues loading step"""
    
    logger.info("="*50)
    logger.info("LOADING OSMOSE ISSUES ONLY")
    logger.info("="*50)
    
    try:
        issues_loader = OsmoseIssuesLoader()
        batch_id = issues_loader.run(limit=limit)
        
        if batch_id:
            logger.info(f"✓ Successfully loaded issues (Batch ID: {batch_id})")
            return True
        else:
            logger.error("Failed to load issues")
            return False
            
    except Exception as e:
        logger.error(f"Issues loading failed: {e}")
        return False

def run_patches_only(country_code: str = None):
    """Run only the patches creation step"""
    
    logger.info("="*50)
    logger.info("CREATING PATCHES ONLY")
    logger.info("="*50)
    
    try:
        patches_creator = PatchesCreator()
        batch_id = patches_creator.run(country_code=country_code)
        
        if batch_id:
            logger.info(f"✓ Successfully created patches (Batch ID: {batch_id})")
            return True
        else:
            logger.error("Failed to create patches")
            return False
            
    except Exception as e:
        logger.error(f"Patches creation failed: {e}")
        return False

def check_database_status():
    """Check database status and show summary"""
    
    from utils import get_db_connection, close_db_connection
    from psycopg2.extras import RealDictCursor
    
    logger.info("="*50)
    logger.info("DATABASE STATUS CHECK")
    logger.info("="*50)
    
    try:
        conn = get_db_connection()
        
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Check tables exist
            cur.execute("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_name IN ('import_batches', 'osmose_errors', 'osmose_patches')
                ORDER BY table_name
            """)
            tables = [row['table_name'] for row in cur.fetchall()]
            
            logger.info(f"Tables found: {', '.join(tables) if tables else 'None'}")
            
            if 'osmose_errors' in tables:
                cur.execute("SELECT COUNT(*) as count FROM osmose_errors")
                error_count = cur.fetchone()['count']
                
                cur.execute("""
                    SELECT COUNT(*) as unprocessed 
                    FROM osmose_errors 
                    WHERE patch_id IS NULL
                """)
                unprocessed = cur.fetchone()['unprocessed']
                
                logger.info(f"Total errors: {error_count}")
                logger.info(f"Unprocessed errors: {unprocessed}")
            
            if 'osmose_patches' in tables:
                cur.execute("SELECT COUNT(*) as count FROM osmose_patches")
                patch_count = cur.fetchone()['count']
                
                cur.execute("""
                    SELECT 
                        AVG(area_km2) as avg_area,
                        AVG(error_count) as avg_errors
                    FROM osmose_patches
                """)
                stats = cur.fetchone()
                
                logger.info(f"Total patches: {patch_count}")
                if stats['avg_area']:
                    logger.info(f"Average patch area: {stats['avg_area']:.2f} km²")
                    logger.info(f"Average errors per patch: {stats['avg_errors']:.1f}")
            
            if 'import_batches' in tables:
                cur.execute("""
                    SELECT 
                        batch_id,
                        imported_at,
                        imported_by,
                        new_patches,
                        errors_count
                    FROM import_batches 
                    ORDER BY imported_at DESC 
                    LIMIT 5
                """)
                batches = cur.fetchall()
                
                if batches:
                    logger.info("\nRecent batches:")
                    for batch in batches:
                        logger.info(f"  {batch['batch_id']}: {batch['imported_by']} "
                                  f"({batch['imported_at'].strftime('%Y-%m-%d %H:%M')})")
        
        close_db_connection(conn)
        return True
        
    except Exception as e:
        logger.error(f"Database check failed: {e}")
        return False

def main():
    """Main function with command line interface"""
    
    parser = argparse.ArgumentParser(
        description='Osmose Processing Pipeline',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_pipeline.py --full --limit 1000     # Run full pipeline with limit
  python run_pipeline.py --issues-only --test    # Load issues only (test mode)
  python run_pipeline.py --patches-only          # Create patches only
  python run_pipeline.py --status                # Check database status
        """
    )
    
    # Mode selection
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument('--full', action='store_true', 
                           help='Run full pipeline (issues + patches)')
    mode_group.add_argument('--issues-only', action='store_true',
                           help='Load Osmose issues only')
    mode_group.add_argument('--patches-only', action='store_true',
                           help='Create patches only')
    mode_group.add_argument('--status', action='store_true',
                           help='Check database status')
    
    # Options
    parser.add_argument('--limit', type=int, 
                       help='Limit number of errors to fetch from API')
    parser.add_argument('--test', action='store_true',
                       help='Run in test mode (small data set)')
    parser.add_argument('--country', 
                       help='Country code filter for patch creation')
    
    args = parser.parse_args()
    
    # Set test limit if requested
    if args.test and not args.limit:
        args.limit = 100
        logger.info("Running in TEST mode with limit=100")
    
    # Run requested operation
    success = False
    
    if args.status:
        success = check_database_status()
    elif args.full:
        success = run_full_pipeline(limit=args.limit, country_code=args.country)
    elif args.issues_only:
        success = run_issues_only(limit=args.limit)
    elif args.patches_only:
        success = run_patches_only(country_code=args.country)
    
    # Exit with appropriate code
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()