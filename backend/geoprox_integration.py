import psycopg2
import psycopg2.extras
import jwt
import bcrypt
import hashlib
import binascii
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
import json
import os
from contextlib import contextmanager

# GeoProx Production Database Configuration - Public Instance (Working)
# Using IP address due to DNS resolution issues in container environment
# Hostname: geoprox-serverless-public-instance-1.c3ooecias6w8.eu-west-1.rds.amazonaws.com
GEOPROX_DB_CONFIG = {
    "host": "176.34.196.217",
    "database": "geoprox", 
    "user": "GeoProx_V2",
    "password": "Glidepath25!",
    "port": 5432,
    "sslmode": "require",
    "connect_timeout": 10  # 10 second timeout for connection attempts
}

# JWT Configuration
JWT_SECRET_KEY = "geoprox-mobile-secret-2025"  # In production, use proper secret management
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 24

class GeoProxDatabase:
    """Database connection manager for GeoProx production database"""
    
    @contextmanager
    def get_connection(self):
        conn = None
        try:
            conn = psycopg2.connect(**GEOPROX_DB_CONFIG)
            conn.autocommit = False
            yield conn
        except Exception as e:
            if conn:
                conn.rollback()
            raise e
        finally:
            if conn:
                conn.close()

class GeoProxAuth:
    """JWT Authentication for Mobile App"""
    
    def __init__(self, db: GeoProxDatabase):
        self.db = db
    
    def authenticate_user(self, username: str, password: str) -> Optional[Dict[str, Any]]:
        """Authenticate user against GeoProx users table"""
        with self.db.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute("""
                    SELECT id, username, password_hash, salt, license_tier, is_admin, company_id
                    FROM users 
                    WHERE username = %s AND is_active = true
                """, (username,))
                
                user = cursor.fetchone()
                if not user:
                    return None
                
                # GeoProx uses PBKDF2-HMAC-SHA256 with 120,000 iterations
                # Salt and hash are stored as hex strings
                if user['password_hash'] and user['salt']:
                    try:
                        # Convert hex salt to bytes
                        salt_bytes = binascii.unhexlify(user['salt'])
                        
                        # Compute PBKDF2-HMAC-SHA256 hash (120,000 iterations)
                        computed_hash_bytes = hashlib.pbkdf2_hmac(
                            'sha256',
                            password.encode('utf-8'),
                            salt_bytes,
                            120_000
                        )
                        
                        # Convert to hex for comparison
                        computed_hash_hex = computed_hash_bytes.hex()
                        
                        if computed_hash_hex == user['password_hash']:
                            return dict(user)
                    except (ValueError, binascii.Error) as e:
                        # Invalid salt format
                        pass
                
                return None
    
    def create_jwt_token(self, user: Dict[str, Any]) -> str:
        """Create JWT token for mobile app"""
        payload = {
            "user_id": user["id"],
            "username": user["username"],
            "license_tier": user["license_tier"],
            "is_admin": user.get("is_admin", False),
            "company_id": user.get("company_id"),
            "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRATION_HOURS),
            "iat": datetime.utcnow(),
            "iss": "geoprox-mobile"
        }
        return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    
    def verify_jwt_token(self, token: str) -> Optional[Dict[str, Any]]:
        """Verify and decode JWT token"""
        try:
            payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
            return payload
        except jwt.ExpiredSignatureError:
            return None
        except jwt.InvalidTokenError:
            return None
    
    def refresh_token(self, token: str) -> Optional[str]:
        """Refresh JWT token if valid"""
        payload = self.verify_jwt_token(token)
        if not payload:
            return None
        
        # Get fresh user data
        with self.db.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute("""
                    SELECT id, username, license_tier, is_admin, company_id
                    FROM users 
                    WHERE id = %s AND is_active = true
                """, (payload["user_id"],))
                
                user = cursor.fetchone()
                if user:
                    return self.create_jwt_token(dict(user))
        
        return None

class GeoProxPermits:
    """GeoProx Permits Integration"""
    
    def __init__(self, db: GeoProxDatabase):
        self.db = db
    
    def get_user_permits(self, username: str, search_query: str = "") -> List[Dict[str, Any]]:
        """Get all permits for user's company from GeoProx permit_records table"""
        with self.db.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                # Get user's company_id
                cursor.execute("SELECT company_id FROM users WHERE username = %s", (username,))
                user = cursor.fetchone()
                if not user or not user['company_id']:
                    return []
                
                company_id = user['company_id']
                
                # Get all permits for users in the same company
                base_query = """
                    SELECT DISTINCT
                        pr.permit_ref,
                        pr.username,
                        pr.location_lat,
                        pr.location_lon,
                        pr.desktop_status,
                        pr.desktop_outcome,
                        pr.desktop_summary,
                        pr.site_status,
                        pr.site_payload,
                        pr.sample_status,
                        pr.sample_payload,
                        pr.search_result,
                        pr.created_at,
                        pr.updated_at
                    FROM permit_records pr
                    INNER JOIN users u ON pr.username = u.username
                    WHERE u.company_id = %s
                """
                
                params = [company_id]
                
                if search_query.strip():
                    base_query += " AND permit_ref ILIKE %s"
                    params.append(f"%{search_query}%")
                
                base_query += " ORDER BY updated_at DESC"
                
                cursor.execute(base_query, params)
                permits = cursor.fetchall()
                
                # Convert to mobile app format
                mobile_permits = []
                for permit in permits:
                    mobile_permit = self._convert_to_mobile_format(permit)
                    mobile_permits.append(mobile_permit)
                
                return mobile_permits
    
    def get_permit_details(self, username: str, permit_ref: str) -> Optional[Dict[str, Any]]:
        """Get detailed permit information"""
        with self.db.get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute("""
                    SELECT * FROM permit_records 
                    WHERE username = %s AND permit_ref = %s
                """, (username, permit_ref))
                
                permit = cursor.fetchone()
                if permit:
                    return self._convert_to_mobile_format(permit)
                return None
    
    def _convert_to_mobile_format(self, permit: Dict[str, Any]) -> Dict[str, Any]:
        """Convert GeoProx permit format to mobile app format"""
        
        # Parse desktop summary for proximity assessment
        desktop_summary = permit.get('desktop_summary') or {}
        if isinstance(desktop_summary, str):
            try:
                desktop_summary = json.loads(desktop_summary)
            except:
                desktop_summary = {}
        
        # Parse site payload for inspection results
        site_payload = permit.get('site_payload') or {}
        if isinstance(site_payload, str):
            try:
                site_payload = json.loads(site_payload)
            except:
                site_payload = {}
        
        # Parse sample payload for sample results
        sample_payload = permit.get('sample_payload') or {}
        if isinstance(sample_payload, str):
            try:
                sample_payload = json.loads(sample_payload)
            except:
                sample_payload = {}
        
        # Extract proximity risk assessment
        proximity_risk = "LOW"  # Default
        if desktop_summary.get('risk_assessment'):
            proximity_risk = desktop_summary['risk_assessment'].upper()
        
        # Extract site inspection status and results
        inspection_status = permit.get('site_status', 'pending').lower()
        inspection_results = None
        if inspection_status == 'completed' and site_payload:
            inspection_results = {
                "bituminous": site_payload.get('bituminous_result', ''),
                "sub_base": site_payload.get('sub_base_result', '')
            }
        
        # Extract sample testing status and results
        sample_status = permit.get('sample_status', 'not_required').lower()
        sample_results = None
        if sample_status == 'completed' and sample_payload:
            sample_results = self._extract_sample_results(sample_payload)
        
        return {
            "id": permit['permit_ref'],  # Use permit_ref as ID for mobile
            "permit_ref": permit['permit_ref'],  # Frontend expects this field
            "permit_number": permit['permit_ref'],
            "works_type": "Standard",  # Default, could be extracted from search_result
            "location": "Public",  # Default, could be extracted from search_result  
            "address": f"{permit.get('location_lat', 0)}, {permit.get('location_lon', 0)}",
            "latitude": float(permit.get('location_lat') or 0),
            "longitude": float(permit.get('location_lon') or 0),
            "highway_authority": "Unknown",  # Could be extracted from search_result
            "status": "Active",
            "proximity_risk_assessment": proximity_risk,
            "desktop_outcome": permit.get('desktop_outcome', 'N/A'),
            "owner": permit.get('username', 'N/A'),
            "created_at": permit.get('created_at', '').isoformat() if permit.get('created_at') else '',
            "inspection_status": inspection_status,
            "inspection_results": inspection_results,
            "sample_status": sample_status,
            "sample_results": sample_results
        }
    
    def _extract_sample_results(self, sample_payload: Dict[str, Any]) -> Dict[str, Any]:
        """Extract sample results from sample payload"""
        results = {}
        
        # Sample 1 determinants
        sample1_determinants = []
        determinants = ['coal_tar', 'petroleum', 'heavy_metal', 'asbestos', 'other']
        
        for det in determinants:
            result_key = f"{det}_sample1"
            conc_key = f"{det}_conc1"
            if sample_payload.get(result_key) or sample_payload.get(conc_key):
                sample1_determinants.append({
                    "name": det.replace('_', ' ').title(),
                    "result": sample_payload.get(result_key, ''),
                    "concentration": sample_payload.get(conc_key, '')
                })
        
        if sample1_determinants:
            results["sample1_determinants"] = sample1_determinants
        
        # Sample 2 determinants  
        sample2_determinants = []
        for det in determinants:
            result_key = f"{det}_sample2"
            conc_key = f"{det}_conc2"
            if sample_payload.get(result_key) or sample_payload.get(conc_key):
                sample2_determinants.append({
                    "name": det.replace('_', ' ').title(),
                    "result": sample_payload.get(result_key, ''),
                    "concentration": sample_payload.get(conc_key, '')
                })
        
        if sample2_determinants:
            results["sample2_determinants"] = sample2_determinants
        
        return results
    
    def save_site_inspection(self, username: str, permit_ref: str, inspection_data: Dict[str, Any], is_draft: bool = False) -> bool:
        """Save site inspection to GeoProx permit_records"""
        with self.db.get_connection() as conn:
            with conn.cursor() as cursor:
                status = "wip" if is_draft else "completed"
                payload = json.dumps(inspection_data)
                
                cursor.execute("""
                    UPDATE permit_records 
                    SET site_status = %s, site_payload = %s, updated_at = %s
                    WHERE username = %s AND permit_ref = %s
                """, (status, payload, datetime.utcnow(), username, permit_ref))
                
                conn.commit()
                return cursor.rowcount > 0
    
    def save_sample_testing(self, username: str, permit_ref: str, sample_data: Dict[str, Any], is_draft: bool = False) -> bool:
        """Save sample testing to GeoProx permit_records"""
        with self.db.get_connection() as conn:
            with conn.cursor() as cursor:
                status = "wip" if is_draft else "completed"
                payload = json.dumps(sample_data)
                
                cursor.execute("""
                    UPDATE permit_records 
                    SET sample_status = %s, sample_payload = %s, updated_at = %s
                    WHERE username = %s AND permit_ref = %s
                """, (status, payload, datetime.utcnow(), username, permit_ref))
                
                conn.commit()
                return cursor.rowcount > 0

# Global instances
geoprox_db = GeoProxDatabase()
geoprox_auth = GeoProxAuth(geoprox_db)
geoprox_permits = GeoProxPermits(geoprox_db)