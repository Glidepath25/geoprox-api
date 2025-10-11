#!/usr/bin/env python3
"""
Debug script to check GeoProx database schema
"""

import psycopg2
import psycopg2.extras
from backend.geoprox_integration import GEOPROX_DB_CONFIG

def check_database_schema():
    """Check what columns exist in permit_records table"""
    try:
        conn = psycopg2.connect(**GEOPROX_DB_CONFIG)
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            # Get table schema
            cursor.execute("""
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns 
                WHERE table_name = 'permit_records'
                ORDER BY ordinal_position;
            """)
            
            columns = cursor.fetchall()
            print("📋 PERMIT_RECORDS TABLE SCHEMA:")
            print("=" * 50)
            for col in columns:
                print(f"  {col['column_name']:<25} {col['data_type']:<15} {'NULL' if col['is_nullable'] == 'YES' else 'NOT NULL'}")
            
            print("\n🔍 SAMPLE DATA:")
            print("=" * 50)
            # Get sample data
            cursor.execute("""
                SELECT * FROM permit_records 
                WHERE username = 'EXPOTEST' 
                LIMIT 3;
            """)
            
            records = cursor.fetchall()
            if records:
                print(f"Found {len(records)} records for EXPOTEST:")
                for i, record in enumerate(records, 1):
                    print(f"\nRecord {i}:")
                    for key, value in record.items():
                        if value is not None:
                            print(f"  {key}: {str(value)[:100]}{'...' if len(str(value)) > 100 else ''}")
            else:
                print("No records found for EXPOTEST user")
                
                # Check if user exists at all
                cursor.execute("SELECT COUNT(*) as count FROM permit_records WHERE username = 'EXPOTEST'")
                count = cursor.fetchone()['count']
                print(f"Total EXPOTEST records: {count}")
                
                # Check what users exist
                cursor.execute("SELECT DISTINCT username FROM permit_records LIMIT 10")
                users = cursor.fetchall()
                print(f"Sample usernames in database: {[u['username'] for u in users]}")
        
        conn.close()
        return True
        
    except Exception as e:
        print(f"❌ Database connection error: {e}")
        return False

if __name__ == "__main__":
    check_database_schema()