#!/usr/bin/env python3
"""
Maintenance and Cleanup Script for Osmose Processing Pipeline
"""

import argparse
from datetime import datetime, timedelta
from typing import List, Dict
from psycopg2.extras import RealDictCursor

from utils import get_db_connection, close_db_connection, setup_logging

logger = setup_logging()

class MaintenanceManager:
    """Handles maintenance and cleanup operations"""
    
    def __init__(self):
        self.conn = None
        
    def connect_db(self):
        """Connect to database"""
        self.conn = get_db_connection()
        logger.info("Connected to database")
            
    def close_db(self):
        """Close database connection"""
        if self.conn:
            close_db_connection(self.conn)
            
    def cleanup_old_batches(self, days_old: int = 30) -> int:
        """Remove import batches older than specified days"""
        cutoff_date = datetime.now() - timedelta(days=days_old)
        
        with self.conn.cursor() as cur:
            # Get batches to delete
            cur.execute("""
                SELECT batch_id, imported_at, imported_by 
                FROM import_batches 
                WHERE imported_at < %s
                ORDER BY imported_at
            """, (cutoff_date,))
            
            old_batches = cur.fetchall()
            
            if not old_batches:
                logger.info(f"No batches older than {days_old} days found")
                return 0
            
            logger.info(f"Found {len(old_batches)} batches to delete")
            
            # Delete old batches (cascading deletes will handle related records)
            batch_ids = [batch[0] for batch in old_batches]
            
            cur.execute("""
                DELETE FROM import_batches 
                WHERE batch_id = ANY(%s)
            """, (batch_ids,))
            
            deleted_count = cur.rowcount
            self.conn.commit()
            
            logger.info(f"Deleted {deleted_count} old import batches")
            return deleted_count
            
    def remove_orphaned_errors(self) -> int:
        """Remove osmose_errors that reference non-existent patches"""
        with self.conn.cursor() as cur:
            cur.execute("""
                UPDATE osmose_errors 
                SET patch_id = NULL 
                WHERE patch_id IS NOT NULL 
                AND patch_id NOT IN (SELECT patch_id FROM osmose_patches)
            """)
            
            updated_count = cur.rowcount
            self.conn.commit()
            
            logger.info(f"Cleaned up {updated_count} orphaned error references")
            return updated_count
            
    def reset_unprocessed_errors(self) -> int:
        """Reset all errors to unprocessed state (remove patch assignments)"""
        with self.conn.cursor() as cur:
            cur.execute("""
                UPDATE osmose_errors 
                SET patch_id = NULL, updated_at = CURRENT_TIMESTAMP
                WHERE patch_id IS NOT NULL
            """)
            
            updated_count = cur.rowcount
            self.conn.commit()
            
            logger.info(f"Reset {updated_count} errors to unprocessed state")
            return updated_count
            
    def delete_all_patches(self) -> int:
        """Delete all patches (for complete reset)"""
        with self.conn.cursor() as cur:
            # First, unlink errors from patches
            cur.execute("""
                UPDATE osmose_errors 
                SET patch_id = NULL 
                WHERE patch_id IS NOT NULL
            """)
            
            # Then delete all patches
            cur.execute("DELETE FROM osmose_patches")
            deleted_count = cur.rowcount
            
            self.conn.commit()
            
            logger.info(f"Deleted all {deleted_count} patches")
            return deleted_count
            
    def vacuum_database(self):
        """Run VACUUM on all tables to reclaim space"""
        # Note: VACUUM cannot be run inside a transaction
        old_autocommit = self.conn.autocommit
        self.conn.autocommit = True
        
        try:
            with self.conn.cursor() as cur:
                logger.info("Running VACUUM on osmose_errors...")
                cur.execute("VACUUM ANALYZE osmose_errors")
                
                logger.info("Running VACUUM on osmose_patches...")
                cur.execute("VACUUM ANALYZE osmose_patches")
                
                logger.info("Running VACUUM on import_batches...")
                cur.execute("VACUUM ANALYZE import_batches")
                
            logger.info("Database vacuum completed")
            
        finally:
            self.conn.autocommit = old_autocommit
            
    def get_database_stats(self) -> Dict:
        """Get comprehensive database statistics"""
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            stats = {}
            
            # Table sizes
            cur.execute("""
                SELECT 
                    schemaname,
                    tablename,
                    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) as size
                FROM pg_tables 
                WHERE schemaname = 'public' 
                AND tablename IN ('osmose_errors', 'osmose_patches', 'import_batches')
                ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC
            """)
            stats['table_sizes'] = cur.fetchall()
            
            # Record counts
            cur.execute("SELECT COUNT(*) as count FROM osmose_errors")
            stats['total_errors'] = cur.fetchone()['count']
            
            cur.execute("SELECT COUNT(*) as count FROM osmose_errors WHERE patch_id IS NULL")
            stats['unprocessed_errors'] = cur.fetchone()['count']
            
            cur.execute("SELECT COUNT(*) as count FROM osmose_patches")
            stats['total_patches'] = cur.fetchone()['count']
            
            cur.execute("SELECT COUNT(*) as count FROM import_batches")
            stats['total_batches'] = cur.fetchone()['count']
            
            # Patch statistics
            cur.execute("""
                SELECT 
                    AVG(area_km2) as avg_area,
                    MIN(area_km2) as min_area,
                    MAX(area_km2) as max_area,
                    AVG(error_count) as avg_errors,
                    MIN(error_count) as min_errors,
                    MAX(error_count) as max_errors
                FROM osmose_patches
            """)
            patch_stats = cur.fetchone()
            stats['patch_statistics'] = dict(patch_stats) if patch_stats['avg_area'] else {}
            
            # Recent activity
            cur.execute("""
                SELECT 
                    batch_id,
                    imported_at,
                    imported_by,
                    new_patches,
                    errors_count
                FROM import_batches 
                ORDER BY imported_at DESC 
                LIMIT 10
            """)
            stats['recent_batches'] = cur.fetchall()
            
            return stats
            
    def print_database_report(self):
        """Print comprehensive database report"""
        stats = self.get_database_stats()
        
        logger.info("="*60)
        logger.info("DATABASE MAINTENANCE REPORT")
        logger.info("="*60)
        
        # Table sizes
        logger.info("\nTable Sizes:")
        for table in stats['table_sizes']:
            logger.info(f"  {table['tablename']}: {table['size']}")
        
        # Record counts
        logger.info(f"\nRecord Counts:")
        logger.info(f"  Total errors: {stats['total_errors']:,}")
        logger.info(f"  Unprocessed errors: {stats['unprocessed_errors']:,}")
        logger.info(f"  Total patches: {stats['total_patches']:,}")
        logger.info(f"  Import batches: {stats['total_batches']:,}")
        
        # Patch statistics
        if stats['patch_statistics']:
            ps = stats['patch_statistics']
            logger.info(f"\nPatch Statistics:")
            logger.info(f"  Average area: {ps['avg_area']:.2f} km² "
                       f"(min: {ps['min_area']:.2f}, max: {ps['max_area']:.2f})")
            logger.info(f"  Average errors: {ps['avg_errors']:.1f} "
                       f"(min: {ps['min_errors']}, max: {ps['max_errors']})")
        
        # Recent activity
        if stats['recent_batches']:
            logger.info(f"\nRecent Import Batches:")
            for batch in stats['recent_batches'][:5]:
                logger.info(f"  {batch['batch_id']}: {batch['imported_by']} "
                           f"({batch['imported_at'].strftime('%Y-%m-%d %H:%M')}) "
                           f"- {batch['new_patches']} patches, {batch['errors_count']} errors")
        
        logger.info("="*60)
        
    def run_maintenance(self, operations: List[str]):
        """Run specified maintenance operations"""
        try:
            self.connect_db()
            
            for operation in operations:
                logger.info(f"\nRunning operation: {operation}")
                
                if operation == 'cleanup_old_batches':
                    self.cleanup_old_batches(days_old=30)
                elif operation == 'remove_orphaned_errors':
                    self.remove_orphaned_errors()
                elif operation == 'reset_errors':
                    self.reset_unprocessed_errors()
                elif operation == 'delete_patches':
                    self.delete_all_patches()
                elif operation == 'vacuum':
                    self.vacuum_database()
                elif operation == 'report':
                    self.print_database_report()
                else:
                    logger.warning(f"Unknown operation: {operation}")
                    
        except Exception as e:
            logger.error(f"Maintenance failed: {e}")
            raise
        finally:
            self.close_db()

def main():
    """Main function"""
    parser = argparse.ArgumentParser(
        description='Database Maintenance and Cleanup',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Available Operations:
  cleanup_old_batches  - Remove import batches older than 30 days
  remove_orphaned_errors - Clean up error references to deleted patches
  reset_errors         - Reset all errors to unprocessed state
  delete_patches       - Delete all patches (DESTRUCTIVE!)
  vacuum              - Run VACUUM ANALYZE on all tables
  report              - Generate database statistics report

Examples:
  python maintenance.py --report
  python maintenance.py --operations cleanup_old_batches vacuum
  python maintenance.py --operations reset_errors delete_patches --confirm
        """
    )
    
    parser.add_argument('--operations', nargs='+',
                       choices=['cleanup_old_batches', 'remove_orphaned_errors', 
                               'reset_errors', 'delete_patches', 'vacuum', 'report'],
                       help='Maintenance operations to run')
    
    parser.add_argument('--report', action='store_true',
                       help='Generate database report only')
    
    parser.add_argument('--confirm', action='store_true',
                       help='Required for destructive operations')
    
    args = parser.parse_args()
    
    # Default to report if no operations specified
    if not args.operations and not args.report:
        args.operations = ['report']
    elif args.report and not args.operations:
        args.operations = ['report']
    
    # Check for destructive operations
    destructive_ops = {'reset_errors', 'delete_patches'}
    if args.operations and any(op in destructive_ops for op in args.operations):
        if not args.confirm:
            logger.error("Destructive operations require --confirm flag")
            logger.error(f"Destructive operations requested: {destructive_ops & set(args.operations)}")
            return 1
        
        logger.warning("DESTRUCTIVE OPERATIONS CONFIRMED!")
        logger.warning(f"Operations: {destructive_ops & set(args.operations)}")
        
        response = input("Type 'YES' to continue: ")
        if response != 'YES':
            logger.info("Operation cancelled")
            return 0
    
    # Run maintenance
    manager = MaintenanceManager()
    manager.run_maintenance(args.operations)
    
    logger.info("Maintenance completed successfully")
    return 0

if __name__ == "__main__":
    exit(main())