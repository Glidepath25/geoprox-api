from fastapi import FastAPI, APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
import uuid
from datetime import datetime
import hashlib
import jwt
from bson import ObjectId

# Import GeoProx Integration
from .geoprox_integration import geoprox_auth, geoprox_permits, geoprox_db

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
client = AsyncIOMotorClient(mongo_url, serverSelectionTimeoutMS=5000)
db_name = os.environ.get('DB_NAME', 'geoprox_mobile')
db = client[db_name]

# Feature flag that decides whether to call the production GeoProx database.
# Disable (set to "0") to work purely with the local sample data.
USE_GEOPROX_PROD = os.environ.get("USE_GEOPROX_PROD", "1") == "1"

# Create the main app
app = FastAPI()
api_router = APIRouter(prefix="/api")

# Security
security = HTTPBearer()
security_optional = HTTPBearer(auto_error=False)
JWT_SECRET = "geoprox-secret-key-2025"

# Models
class User(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    username: str
    email: str
    password_hash: str
    created_at: datetime = Field(default_factory=datetime.utcnow)

class UserLogin(BaseModel):
    username: str
    password: str

class UserResponse(BaseModel):
    id: str
    username: str
    email: str

class Permit(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    permit_number: str
    works_type: str
    location: str
    address: str
    latitude: float
    longitude: float
    highway_authority: str
    status: str
    proximity_risk_assessment: str  # Result from desktop assessment
    created_by: str
    created_at: datetime = Field(default_factory=datetime.utcnow)

class SiteInspection(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    permit_id: str
    inspector_id: str
    inspection_date: datetime = Field(default_factory=datetime.utcnow)
    work_order_reference: str
    excavation_site_number: str
    surface_location: str
    utility_type: str  # User enters this on site
    
    # Questionnaire answers - Optional for draft saves
    q1_asbestos: Optional[str] = ""
    q1_notes: str = ""
    q2_binder_shiny: Optional[str] = ""
    q2_notes: str = ""
    q3_spray_pak: Optional[str] = ""
    q3_notes: str = ""
    q4_soil_stained: Optional[str] = ""
    q4_notes: str = ""
    q5_water_moisture: Optional[str] = ""
    q5_notes: str = ""
    q6_pungent_odours: Optional[str] = ""
    q6_notes: str = ""
    q7_litmus_paper: Optional[str] = ""
    q7_notes: str = ""
    
    # Assessment results - Optional for draft saves
    bituminous_result: Optional[str] = ""
    sub_base_result: Optional[str] = ""
    
    # Photos (base64 encoded)
    photos: List[str] = []
    
    status: str = "pending"  # pending, wip, completed

class SampleTesting(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    permit_id: str
    inspector_id: str
    testing_date: datetime = Field(default_factory=datetime.utcnow)
    sample_status: str  # Pending sample, Complete, etc.
    sampling_date: Optional[datetime] = None
    results_recorded_by: str = ""
    sampled_by: str = ""
    notes: str = ""
    comments: str = ""
    
    # Sample 1 details
    sample1_number: str = ""
    sample1_material: str = ""
    sample1_lab_analysis: str = ""
    
    # Sample 2 details  
    sample2_number: str = ""
    sample2_material: str = ""
    sample2_lab_analysis: str = ""
    
    # Determinant results for both samples
    coal_tar_sample1: str = ""
    coal_tar_sample2: str = ""
    petroleum_sample1: str = ""
    petroleum_sample2: str = ""
    heavy_metal_sample1: str = ""
    heavy_metal_sample2: str = ""
    asbestos_sample1: str = ""
    asbestos_sample2: str = ""
    other_sample1: str = ""
    other_sample2: str = ""
    
    # Concentration values
    coal_tar_conc1: str = ""
    coal_tar_conc2: str = ""
    petroleum_conc1: str = ""  
    petroleum_conc2: str = ""
    heavy_metal_conc1: str = ""
    heavy_metal_conc2: str = ""
    asbestos_conc1: str = ""
    asbestos_conc2: str = ""
    other_conc1: str = ""
    other_conc2: str = ""
    
    # Attachments
    field_photos: List[str] = []
    lab_results: List[str] = []
    general_attachments: List[str] = []
    
    status: str = "pending"  # pending, wip, completed

class SampleTestingCreate(BaseModel):
    permit_ref: str
    form_data: dict  # Flexible form data from mobile

class InspectionCreate(BaseModel):
    permit_ref: str
    form_data: dict  # Flexible form data from mobile

class MobileRefreshRequest(BaseModel):
    refresh_token: Optional[str] = None

# Helper functions
def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def verify_password(password: str, hash: str) -> bool:
    return hash_password(password) == hash

def create_token(user_id: str) -> str:
    payload = {"user_id": user_id, "exp": datetime.utcnow().timestamp() + 86400}  # 24 hours
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")

LOCAL_SAMPLE_USERS = [
    {
        "id": "local-user-1",
        "username": "demo.user",
        "email": "demo@geoprox.com",
        "password_hash": hash_password("password123"),
        "license_tier": "LOCAL",
        "is_admin": False,
    },
]

LOCAL_SAMPLE_PERMITS = [
    {
        "id": "local-permit-1",
        "permit_number": "DEMO-0001",
        "works_type": "Standard",
        "location": "Public",
        "address": "Demo Street, Demo City",
        "latitude": 53.35,
        "longitude": -6.26,
        "highway_authority": "Demo Authority",
        "status": "Active",
        "proximity_risk_assessment": "LOW",
        "created_by": "local-user-1",
        "created_at": datetime.utcnow(),
    },
    {
        "id": "local-permit-2",
        "permit_number": "DEMO-0002",
        "works_type": "Emergency",
        "location": "Private",
        "address": "Industrial Estate, Demo City",
        "latitude": 53.38,
        "longitude": -6.3,
        "highway_authority": "Demo Authority",
        "status": "Active",
        "proximity_risk_assessment": "MEDIUM",
        "created_by": "local-user-1",
        "created_at": datetime.utcnow(),
    },
]

LOCAL_INSPECTION_STORAGE: Dict[str, dict] = {}
LOCAL_SAMPLE_STORAGE: Dict[str, dict] = {}

async def authenticate_local_user(username: str, password: str) -> Optional[dict]:
    """Validate credentials against the local Mongo sample dataset."""
    try:
        user = await db.users.find_one({"username": username})
        if user and verify_password(password, user["password_hash"]):
            return user
    except Exception as e:
        logging.warning(f"Mongo unavailable during local auth lookup: {e}")
    for user in LOCAL_SAMPLE_USERS:
        if user["username"] == username and verify_password(password, user["password_hash"]):
            return user
    return None

def build_local_login_response(user: dict) -> dict:
    """Return a login payload that mirrors the GeoProx response format."""
    token = create_token(user["id"])
    return {
        "access_token": token,
        "refresh_token": token,
        "expires_in": 86400,
        "refresh_expires_in": 86400,
        "token_type": "Bearer",
        "user": {
            "id": user["id"],
            "username": user["username"],
            "license_tier": user.get("license_tier", "LOCAL"),
            "is_admin": user.get("is_admin", False),
        },
        "mode": "local",
    }

def _datetime_to_iso(value: Optional[datetime]) -> str:
    return value.isoformat() if isinstance(value, datetime) else ""

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=["HS256"])
        user_id = payload.get("user_id")
        user = await db.users.find_one({"id": user_id})
        if user:
            return User(**user)
    except:
        pass
    raise HTTPException(status_code=401, detail="Invalid token")

# Initialize sample data
async def init_sample_data():
    if os.getenv("SKIP_MONGO_INIT", "0") == "1":
        logging.info("SKIP_MONGO_INIT=1 -> skipping Mongo sample data init")
        return
    # Clear existing data to ensure schema compatibility
    await db.users.delete_many({})
    await db.permits.delete_many({})
    await db.inspections.delete_many({})
    
    # Check if users exist
    user_count = await db.users.count_documents({})
    if user_count == 0:
        # Create sample users
        sample_users = [
            {
                "id": str(uuid.uuid4()),
                "username": "john.smith",
                "email": "john@geoprox.com",
                "password_hash": hash_password("password123"),
                "created_at": datetime.utcnow()
            },
            {
                "id": str(uuid.uuid4()),
                "username": "sarah.jones",
                "email": "sarah@geoprox.com", 
                "password_hash": hash_password("password123"),
                "created_at": datetime.utcnow()
            }
        ]
        await db.users.insert_many(sample_users)
        
        # Create sample permits  
        sample_permits = [
            {
                "id": str(uuid.uuid4()),
                "permit_number": "K6004-HAW-VON-59848",
                "works_type": "Standard",
                "location": "Public",
                "address": "Howth Road Junction, Dublin",
                "latitude": 53.390323,
                "longitude": -2.851263,
                "highway_authority": "Howth",
                "status": "Active",
                "proximity_risk_assessment": "MEDIUM",
                "created_by": sample_users[0]["id"],
                "created_at": datetime.utcnow()
            },
            {
                "id": str(uuid.uuid4()),
                "permit_number": "Test123-HAW-GAS-12345", 
                "works_type": "Emergency",
                "location": "Private",
                "address": "Industrial Estate, Manchester",
                "latitude": 54.123456,
                "longitude": -3.234567,
                "highway_authority": "Manchester",
                "status": "Active",
                "proximity_risk_assessment": "HIGH",
                "sample_required": "pending_sample",  # This permit needs sampling
                "created_by": sample_users[0]["id"],
                "created_at": datetime.utcnow()
            },
            {
                "id": str(uuid.uuid4()),
                "permit_number": "ELEC789-BIR-POW-67890",
                "works_type": "Planned",
                "location": "Public",
                "address": "City Centre, Birmingham",
                "latitude": 52.487654,
                "longitude": -1.876543,
                "highway_authority": "Birmingham",
                "status": "Active",
                "proximity_risk_assessment": "LOW", 
                "created_by": sample_users[1]["id"],
                "created_at": datetime.utcnow()
            },
            # Additional K6001-Daff permits for testing
            {
                "id": str(uuid.uuid4()),
                "permit_number": "K6001-Daff-ABC-1234",
                "works_type": "Standard",
                "location": "Public",
                "address": "Main Street, Cork",
                "latitude": 51.8969,
                "longitude": -8.4863,
                "highway_authority": "Cork",
                "status": "Active",
                "proximity_risk_assessment": "LOW",
                "sample_required": "pending_sample",
                "created_by": sample_users[0]["id"],
                "created_at": datetime.utcnow()
            },
            {
                "id": str(uuid.uuid4()),
                "permit_number": "K6001-Daff-XYZ-5678",
                "works_type": "Emergency",
                "location": "Private",
                "address": "Industrial Park, Galway",
                "latitude": 53.2707,
                "longitude": -9.0568,
                "highway_authority": "Galway",
                "status": "Active",
                "proximity_risk_assessment": "HIGH",
                "created_by": sample_users[0]["id"],
                "created_at": datetime.utcnow()
            },
            {
                "id": str(uuid.uuid4()),
                "permit_number": "K6001-Daff-PQR-9012",
                "works_type": "Planned",
                "location": "Public",
                "address": "Town Centre, Limerick",
                "latitude": 52.6638,
                "longitude": -8.6267,
                "highway_authority": "Limerick",
                "status": "Active",
                "proximity_risk_assessment": "MEDIUM",
                "sample_required": "pending_sample",
                "created_by": sample_users[1]["id"],
                "created_at": datetime.utcnow()
            },
            {
                "id": str(uuid.uuid4()),
                "permit_number": "K6001-Daff-LMN-3456",
                "works_type": "Standard",
                "location": "Public",
                "address": "Bridge Street, Waterford",
                "latitude": 52.2593,
                "longitude": -7.1101,
                "highway_authority": "Waterford",
                "status": "Active",
                "proximity_risk_assessment": "LOW",
                "created_by": sample_users[0]["id"],
                "created_at": datetime.utcnow()
            },
            {
                "id": str(uuid.uuid4()),
                "permit_number": "K6001-Daff-RST-7890",
                "works_type": "Emergency",
                "location": "Private",
                "address": "Commercial District, Kilkenny",
                "latitude": 52.6541,
                "longitude": -7.2448,
                "highway_authority": "Kilkenny",
                "status": "Active",
                "proximity_risk_assessment": "HIGH",
                "sample_required": "pending_sample",
                "created_by": sample_users[1]["id"],
                "created_at": datetime.utcnow()
            },
            {
                "id": str(uuid.uuid4()),
                "permit_number": "K6001-Daff-DEF-2468",
                "works_type": "Planned",
                "location": "Public",
                "address": "Market Square, Drogheda",
                "latitude": 53.7158,
                "longitude": -6.3577,
                "highway_authority": "Drogheda",
                "status": "Active",
                "proximity_risk_assessment": "MEDIUM",
                "created_by": sample_users[0]["id"],
                "created_at": datetime.utcnow()
            },
            {
                "id": str(uuid.uuid4()),
                "permit_number": "K6001-Daff-GHI-1357",
                "works_type": "Standard",
                "location": "Private",
                "address": "Business Park, Dundalk",
                "latitude": 54.0018,
                "longitude": -6.4018,
                "highway_authority": "Dundalk",
                "status": "Active",
                "proximity_risk_assessment": "LOW",
                "sample_required": "pending_sample",
                "created_by": sample_users[1]["id"],
                "created_at": datetime.utcnow()
            },
            {
                "id": str(uuid.uuid4()),
                "permit_number": "K6001-Daff-JKL-8024",
                "works_type": "Emergency",
                "location": "Public",
                "address": "High Street, Wexford",
                "latitude": 52.3369,
                "longitude": -6.4633,
                "highway_authority": "Wexford",
                "status": "Active",
                "proximity_risk_assessment": "HIGH",
                "created_by": sample_users[0]["id"],
                "created_at": datetime.utcnow()
            },
            {
                "id": str(uuid.uuid4()),
                "permit_number": "K6001-Daff-MNO-4680",
                "works_type": "Planned",
                "location": "Public",
                "address": "City Center, Sligo",
                "latitude": 54.2766,
                "longitude": -8.4761,
                "highway_authority": "Sligo",
                "status": "Active",
                "proximity_risk_assessment": "MEDIUM",
                "sample_required": "pending_sample",
                "created_by": sample_users[1]["id"],
                "created_at": datetime.utcnow()
            },
            {
                "id": str(uuid.uuid4()),
                "permit_number": "K6001-Daff-VWX-9753",
                "works_type": "Standard",
                "location": "Private",
                "address": "Industrial Zone, Athlone",
                "latitude": 53.4239,
                "longitude": -7.9407,
                "highway_authority": "Athlone",
                "status": "Active",
                "proximity_risk_assessment": "LOW",
                "created_by": sample_users[0]["id"],
                "created_at": datetime.utcnow()
            }
        ]
        await db.permits.insert_many(sample_permits)
        print("Sample data initialized")

# Mobile JWT Authentication Routes
@api_router.post("/mobile/auth/login")
async def mobile_login(user_login: UserLogin):
    """Mobile JWT authentication against production GeoProx database"""
    remote_error: Optional[Exception] = None
    if USE_GEOPROX_PROD:
        try:
            user = geoprox_auth.authenticate_user(user_login.username, user_login.password)
            if user:
                token = geoprox_auth.create_jwt_token(user)
                return {
                    "access_token": token,
                    "refresh_token": token,
                    "expires_in": 86400,
                    "refresh_expires_in": 86400,
                    "token_type": "Bearer",
                    "user": {
                        "id": str(user["id"]),
                        "username": user["username"],
                        "license_tier": user["license_tier"],
                        "is_admin": user.get("is_admin", False),
                    },
                    "mode": "remote",
                }
        except HTTPException:
            raise
        except Exception as e:
            logging.error(f"Mobile login error (remote): {e}")
            remote_error = e

    # Local fallback (either because production is disabled or inaccessible)
    local_user = await authenticate_local_user(user_login.username, user_login.password)
    if local_user:
        logging.info("Using local sample data for mobile login")
        return build_local_login_response(local_user)

    if remote_error:
        error_msg = str(remote_error)
        lowered = error_msg.lower()
        timeout_terms = ["timeout", "timed out", "could not connect", "connection refused"]
        if any(term in lowered for term in timeout_terms):
            raise HTTPException(
                status_code=503,
                detail="Production database unavailable. The GeoProx database cannot be reached. Please contact your administrator.",
            )
        raise HTTPException(status_code=500, detail=f"Authentication service error: {error_msg}")

    raise HTTPException(status_code=401, detail="Invalid credentials")

@api_router.post("/mobile/auth/refresh")
async def mobile_refresh_token(
    body: MobileRefreshRequest | None = None,
    credentials: HTTPAuthorizationCredentials | None = Depends(security_optional),
):
    """Refresh JWT token. Accepts Bearer token or body.refresh_token."""
    token_in = None
    if credentials and credentials.credentials:
        token_in = credentials.credentials
    elif body and body.refresh_token:
        token_in = body.refresh_token

    if not token_in:
        raise HTTPException(status_code=401, detail="Missing token")

    remote_error: Optional[Exception] = None
    if USE_GEOPROX_PROD:
        try:
            new_token = geoprox_auth.refresh_token(token_in)
            if new_token:
                return {
                    "access_token": new_token,
                    "refresh_token": new_token,
                    "expires_in": 86400,
                    "refresh_expires_in": 86400,
                    "token_type": "Bearer",
                }
        except Exception as e:
            logging.warning(f"Remote token refresh failed: {e}")
            remote_error = e

    # Local fallback
    try:
        payload = jwt.decode(token_in, JWT_SECRET, algorithms=["HS256"])
        user = await db.users.find_one({"id": payload.get("user_id")})
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")
        new_token = create_token(user["id"])
        return {
            "access_token": new_token,
            "refresh_token": new_token,
            "expires_in": 86400,
            "refresh_expires_in": 86400,
            "token_type": "Bearer",
        }
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Token refresh error: {e}")
        if remote_error:
            raise HTTPException(status_code=401, detail="Token refresh failed")
        raise HTTPException(status_code=401, detail="Token refresh failed")

@api_router.post("/mobile/auth/logout")
async def mobile_logout(credentials: HTTPAuthorizationCredentials | None = Depends(security_optional)):
    """Stateless logout endpoint for mobile. Always succeeds."""
    return {"message": "Logged out"}

async def _get_local_user_by_username(username: str) -> Optional[dict]:
    try:
        user = await db.users.find_one({"username": username})
        if user:
            return user
    except Exception as e:
        logging.warning(f"Mongo unavailable during user lookup: {e}")
    for user in LOCAL_SAMPLE_USERS:
        if user["username"] == username:
            return user
    return None

async def _get_local_permit_document(permit_ref: str) -> Optional[dict]:
    try:
        permit = await db.permits.find_one({"permit_number": permit_ref})
        if permit:
            return permit
    except Exception as e:
        logging.warning(f"Mongo unavailable during permit lookup: {e}")
    for permit in LOCAL_SAMPLE_PERMITS:
        if permit["permit_number"] == permit_ref:
            return permit
    return None

async def _get_latest_local_record(collection, permit_ref: str, storage: Dict[str, dict]) -> Optional[dict]:
    try:
        record = await collection.find_one(
            {"permit_ref": permit_ref},
            sort=[("updated_at", -1), ("created_at", -1)],
        )
        if record:
            return record
    except Exception as e:
        logging.warning(f"Mongo unavailable during record lookup: {e}")
    return storage.get(permit_ref)

def _extract_site_summary_from_form(form: dict) -> Optional[dict]:
    if not isinstance(form, dict):
        return None
    bituminous = form.get("result_bituminous") or form.get("bituminous_result")
    sub_base = form.get("result_sub_base") or form.get("sub_base_result")
    if bituminous or sub_base:
        return {
            "bituminous": bituminous or "",
            "sub_base": sub_base or "",
        }
    return None

def _extract_sample_summary_from_form(form: dict) -> Optional[dict]:
    if not isinstance(form, dict):
        return None

    def _collect(prefix: str) -> list[dict]:
        items = []
        determinants = [
            ("coal_tar", "Coal tar"),
            ("petroleum", "Petroleum"),
            ("heavy_metal", "Heavy metal"),
            ("asbestos", "Asbestos"),
            ("other", "Other"),
        ]
        for key, label in determinants:
            result = form.get(f"{key}_{prefix}")
            conc = form.get(f"{key}_conc{prefix[-1:]}")
            if result or conc:
                items.append(
                    {
                        "name": label,
                        "result": result or "",
                        "concentration": conc or "",
                    }
                )
        return items

    summary: dict[str, Any] = {}
    sample1 = _collect("sample1")
    if sample1:
        summary["sample1_determinants"] = sample1
    sample2 = _collect("sample2")
    if sample2:
        summary["sample2_determinants"] = sample2

    return summary or None

def _build_location_display(permit: dict) -> dict:
    lat = float(permit.get("latitude") or 0)
    lon = float(permit.get("longitude") or 0)
    display = permit.get("address")
    if not display:
        display = f"{lat}, {lon}"
    return {
        "display": display,
        "lat": lat,
        "lon": lon,
        "radius_m": 0,
    }

async def _convert_local_permit_to_mobile(user: dict, permit: dict) -> dict:
    permit_ref = permit.get("permit_number", permit.get("id"))
    location = _build_location_display(permit)
    desktop_summary = {
        "risk_assessment": permit.get("proximity_risk_assessment", "LOW"),
    }

    inspection_doc = await _get_latest_local_record(db.inspections, permit_ref, LOCAL_INSPECTION_STORAGE)
    site_status = inspection_doc.get("status", "pending") if inspection_doc else "pending"
    site_payload = inspection_doc.get("payload", {}) if inspection_doc else {}
    site_summary = None
    site_notes = inspection_doc.get("notes") if inspection_doc else None
    site_outcome = inspection_doc.get("outcome") if inspection_doc else None
    if site_payload:
        site_summary = _extract_site_summary_from_form(site_payload.get("form", {}))
    if not site_summary and inspection_doc:
        site_summary = {
            "bituminous": inspection_doc.get("bituminous_result", ""),
            "sub_base": inspection_doc.get("sub_base_result", ""),
        } if inspection_doc.get("bituminous_result") or inspection_doc.get("sub_base_result") else None

    sample_doc = await _get_latest_local_record(db.sample_testing, permit_ref, LOCAL_SAMPLE_STORAGE)
    sample_status = sample_doc.get("status", "not_required") if sample_doc else "not_required"
    sample_payload = sample_doc.get("payload", {}) if sample_doc else {}
    sample_notes = sample_doc.get("notes") if sample_doc else None
    sample_outcome = sample_doc.get("outcome") if sample_doc else None
    sample_summary = None
    if sample_payload:
        sample_summary = _extract_sample_summary_from_form(sample_payload.get("form", {}))

    return {
        "permit_ref": permit_ref,
        "created_at": _datetime_to_iso(permit.get("created_at")),
        "updated_at": _datetime_to_iso(permit.get("updated_at", permit.get("created_at"))),
        "owner_username": user.get("username", "local"),
        "owner_display_name": user.get("username", "local"),
        "desktop": {
            "status": permit.get("status", "active").lower(),
            "outcome": permit.get("proximity_risk_assessment"),
            "notes": None,
            "summary": desktop_summary,
            "payload": {},
        },
        "site": {
            "status": site_status,
            "outcome": site_outcome,
            "notes": site_notes,
            "summary": site_summary,
            "payload": site_payload,
        },
        "sample": {
            "status": sample_status,
            "outcome": sample_outcome,
            "notes": sample_notes,
            "summary": sample_summary,
            "payload": sample_payload,
        },
        "location": location,
    }

async def _get_local_permits(username: str, search: str = "") -> List[Dict[str, Any]]:
    user = await _get_local_user_by_username(username)
    if not user:
        return []

    query: dict[str, Any] = {"created_by": user["id"]}
    if search.strip():
        query["permit_number"] = {"$regex": search.strip(), "$options": "i"}

    permits: List[dict] = []
    try:
        permits = await db.permits.find(query).to_list(1000)
    except Exception as e:
        logging.warning(f"Mongo unavailable during permits lookup: {e}")

    if not permits:
        permits = [permit for permit in LOCAL_SAMPLE_PERMITS if permit.get("created_by") == user["id"]] or LOCAL_SAMPLE_PERMITS

    result = []
    for permit in permits:
        converted = await _convert_local_permit_to_mobile(user, permit)
        result.append(converted)
    return result

async def _get_local_permit(username: str, permit_ref: str) -> Optional[Dict[str, Any]]:
    user = await _get_local_user_by_username(username)
    if not user:
        return None
    permit = await _get_local_permit_document(permit_ref)
    if not permit:
        return None
    return await _convert_local_permit_to_mobile(user, permit)

def _prepare_site_payload(form_data: dict, is_draft: bool) -> tuple[dict, str, Optional[str], Optional[str]]:
    if "payload" in form_data:
        payload = form_data.get("payload", {})
        status = form_data.get("status") or ("wip" if is_draft else "completed")
        outcome = form_data.get("outcome")
        notes = form_data.get("notes")
    else:
        payload = {"form": form_data}
        status = "wip" if is_draft else "completed"
        outcome = None
        notes = form_data.get("notes")
    return payload, status.lower(), outcome, notes

async def _save_local_inspection_record(username: str, permit_ref: str, form_data: dict, is_draft: bool) -> Optional[dict]:
    permit = await _get_local_permit_document(permit_ref)
    if not permit:
        return None

    payload, status, outcome, notes = _prepare_site_payload(form_data, is_draft)
    form = payload.get("form", {})
    existing = await db.inspections.find_one({"permit_ref": permit_ref})
    record_id = existing["id"] if existing else str(uuid.uuid4())
    created_at = existing.get("created_at") if existing else datetime.utcnow()

    document = {
        "id": record_id,
        "permit_id": permit["id"],
        "permit_ref": permit_ref,
        "username": username,
        "status": status,
        "outcome": outcome,
        "notes": notes,
        "payload": payload,
        "bituminous_result": form.get("result_bituminous") or form.get("bituminous_result"),
        "sub_base_result": form.get("result_sub_base") or form.get("sub_base_result"),
        "created_at": created_at,
        "updated_at": datetime.utcnow(),
    }

    try:
        await db.inspections.update_one({"id": record_id}, {"$set": document}, upsert=True)
    except Exception as e:
        logging.warning(f"Mongo unavailable when saving inspection: {e}")
    LOCAL_INSPECTION_STORAGE[permit_ref] = document.copy()

    message = "Inspection saved successfully" if is_draft else "Inspection submitted successfully"
    return {"message": message, "status": status}

def _prepare_sample_payload(form_data: dict, is_draft: bool) -> tuple[dict, str, Optional[str], Optional[str]]:
    if "payload" in form_data:
        payload = form_data.get("payload", {})
        status = form_data.get("status") or ("wip" if is_draft else "completed")
        outcome = form_data.get("outcome")
        notes = form_data.get("notes")
    else:
        payload = {"form": form_data}
        status = "wip" if is_draft else "completed"
        outcome = None
        notes = form_data.get("notes")
    return payload, status.lower(), outcome, notes

async def _save_local_sample_record(username: str, permit_ref: str, form_data: dict, is_draft: bool) -> Optional[dict]:
    permit = await _get_local_permit_document(permit_ref)
    if not permit:
        return None

    payload, status, outcome, notes = _prepare_sample_payload(form_data, is_draft)
    form = payload.get("form", {})
    attachments = payload.get("attachments", {})
    existing = await db.sample_testing.find_one({"permit_ref": permit_ref})
    record_id = existing["id"] if existing else str(uuid.uuid4())
    created_at = existing.get("created_at") if existing else datetime.utcnow()

    document = {
        "id": record_id,
        "permit_id": permit["id"],
        "permit_ref": permit_ref,
        "username": username,
        "status": status,
        "outcome": outcome,
        "notes": notes,
        "payload": payload,
        "attachments": attachments,
        "created_at": created_at,
        "updated_at": datetime.utcnow(),
    }

    # Preserve convenience fields for quick lookups
    document.update({
        "sample_status": form.get("sample_status"),
        "sample1_lab_analysis": form.get("sample1_lab_analysis"),
        "sample2_lab_analysis": form.get("sample2_lab_analysis"),
    })

    try:
        await db.sample_testing.update_one({"id": record_id}, {"$set": document}, upsert=True)
    except Exception as e:
        logging.warning(f"Mongo unavailable when saving sample testing: {e}")
    LOCAL_SAMPLE_STORAGE[permit_ref] = document.copy()

    message = "Sample testing saved successfully" if is_draft else "Sample testing submitted successfully"
    return {"message": message, "status": status}

async def get_current_geoprox_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Get current user from JWT token for GeoProx integration"""
    try:
        if USE_GEOPROX_PROD:
            payload = geoprox_auth.verify_jwt_token(credentials.credentials)
            if payload:
                payload["mode"] = "remote"
                return payload
    except Exception as e:
        logging.warning(f"Remote token verification error: {e}")

    # Fallback to local JWT
    try:
        local_payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=["HS256"])
        user = await db.users.find_one({"id": local_payload.get("user_id")})
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")
        return {
            "mode": "local",
            "user_id": user["id"],
            "username": user["username"],
        }
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Token verification error: {e}")
        raise HTTPException(status_code=401, detail="Invalid token")

# Legacy local auth (for backwards compatibility)
@api_router.post("/auth/login")
async def login(user_login: UserLogin):
    user = await db.users.find_one({"username": user_login.username})
    if not user or not verify_password(user_login.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    token = create_token(user["id"])
    return {
        "token": token,
        "user": UserResponse(id=user["id"], username=user["username"], email=user["email"])
    }

# GeoProx Production Integration Routes
@api_router.get("/geoprox/permits")
async def get_geoprox_permits(search: str = "", current_user = Depends(get_current_geoprox_user)):
    """Get permits from production GeoProx database"""
    if current_user.get("mode") == "local" or not USE_GEOPROX_PROD:
        return await _get_local_permits(current_user["username"], search)

    try:
        permits = geoprox_permits.get_user_permits(current_user["username"], search)
        return permits
    except Exception as e:
        logging.error(f"GeoProx permits error: {e}")
        permits = await _get_local_permits(current_user["username"], search)
        if permits:
            logging.info("Serving local permits due to GeoProx production error")
            return permits
        raise HTTPException(status_code=500, detail="Unable to fetch permits from GeoProx")

@api_router.get("/geoprox/permits/{permit_ref}")
async def get_geoprox_permit(permit_ref: str, current_user = Depends(get_current_geoprox_user)):
    """Get specific permit from production GeoProx database"""
    if current_user.get("mode") == "local" or not USE_GEOPROX_PROD:
        permit = await _get_local_permit(current_user["username"], permit_ref)
        if not permit:
            raise HTTPException(status_code=404, detail="Permit not found")
        return permit

    try:
        permit = geoprox_permits.get_permit_details(current_user["username"], permit_ref)
        if not permit:
            raise HTTPException(status_code=404, detail="Permit not found")
        return permit
    except HTTPException:
        raise  # Re-raise HTTPExceptions as-is
    except Exception as e:
        logging.error(f"GeoProx permit details error: {e}")
        permit = await _get_local_permit(current_user["username"], permit_ref)
        if permit:
            logging.info("Serving local permit details due to GeoProx production error")
            return permit
        raise HTTPException(status_code=500, detail="Unable to fetch permit details")

@api_router.post("/geoprox/inspections/save")
async def save_geoprox_inspection(inspection: InspectionCreate, current_user = Depends(get_current_geoprox_user)):
    """Save site inspection to production GeoProx database"""
    if current_user.get("mode") == "local" or not USE_GEOPROX_PROD:
        result = await _save_local_inspection_record(current_user["username"], inspection.permit_ref, inspection.form_data, True)
        if not result:
            raise HTTPException(status_code=404, detail="Permit not found")
        return result

    try:
        success = geoprox_permits.save_site_inspection(
            current_user["username"], 
            inspection.permit_ref, 
            inspection.form_data, 
            is_draft=True
        )
        if success:
            return {"message": "Inspection saved successfully", "status": "wip"}
        result = await _save_local_inspection_record(current_user["username"], inspection.permit_ref, inspection.form_data, True)
        if result:
            logging.info("Saved inspection locally because GeoProx permit was unavailable")
            return result
        raise HTTPException(status_code=404, detail="Permit not found")
    except Exception as e:
        logging.error(f"GeoProx save inspection error: {e}")
        result = await _save_local_inspection_record(current_user["username"], inspection.permit_ref, inspection.form_data, True)
        if result:
            logging.info("Saved inspection locally due to GeoProx production error")
            return result
        raise HTTPException(status_code=500, detail="Unable to save inspection")

@api_router.post("/geoprox/inspections/submit")
async def submit_geoprox_inspection(inspection: InspectionCreate, current_user = Depends(get_current_geoprox_user)):
    """Submit site inspection to production GeoProx database"""
    if current_user.get("mode") == "local" or not USE_GEOPROX_PROD:
        result = await _save_local_inspection_record(current_user["username"], inspection.permit_ref, inspection.form_data, False)
        if not result:
            raise HTTPException(status_code=404, detail="Permit not found")
        return result

    try:
        success = geoprox_permits.save_site_inspection(
            current_user["username"], 
            inspection.permit_ref, 
            inspection.form_data, 
            is_draft=False
        )
        if success:
            return {"message": "Inspection submitted successfully", "status": "completed"}
        result = await _save_local_inspection_record(current_user["username"], inspection.permit_ref, inspection.form_data, False)
        if result:
            logging.info("Submitted inspection locally because GeoProx permit was unavailable")
            return result
        raise HTTPException(status_code=404, detail="Permit not found")
    except Exception as e:
        logging.error(f"GeoProx submit inspection error: {e}")
        result = await _save_local_inspection_record(current_user["username"], inspection.permit_ref, inspection.form_data, False)
        if result:
            logging.info("Submitted inspection locally due to GeoProx production error")
            return result
        raise HTTPException(status_code=500, detail="Unable to submit inspection")

@api_router.post("/geoprox/sample-testing/save")
async def save_geoprox_sample_testing(sample_test: SampleTestingCreate, current_user = Depends(get_current_geoprox_user)):
    """Save sample testing to production GeoProx database"""
    if current_user.get("mode") == "local" or not USE_GEOPROX_PROD:
        result = await _save_local_sample_record(current_user["username"], sample_test.permit_ref, sample_test.form_data, True)
        if not result:
            raise HTTPException(status_code=404, detail="Permit not found")
        return result

    try:
        success = geoprox_permits.save_sample_testing(
            current_user["username"], 
            sample_test.permit_ref, 
            sample_test.form_data, 
            is_draft=True
        )
        if success:
            return {"message": "Sample testing saved successfully", "status": "wip"}
        result = await _save_local_sample_record(current_user["username"], sample_test.permit_ref, sample_test.form_data, True)
        if result:
            logging.info("Saved sample testing locally because GeoProx permit was unavailable")
            return result
        raise HTTPException(status_code=404, detail="Permit not found")
    except Exception as e:
        logging.error(f"GeoProx save sample testing error: {e}")
        result = await _save_local_sample_record(current_user["username"], sample_test.permit_ref, sample_test.form_data, True)
        if result:
            logging.info("Saved sample testing locally due to GeoProx production error")
            return result
        raise HTTPException(status_code=500, detail="Unable to save sample testing")

@api_router.post("/geoprox/sample-testing/submit")
async def submit_geoprox_sample_testing(sample_test: SampleTestingCreate, current_user = Depends(get_current_geoprox_user)):
    """Submit sample testing to production GeoProx database"""
    if current_user.get("mode") == "local" or not USE_GEOPROX_PROD:
        result = await _save_local_sample_record(current_user["username"], sample_test.permit_ref, sample_test.form_data, False)
        if not result:
            raise HTTPException(status_code=404, detail="Permit not found")
        return result

    try:
        success = geoprox_permits.save_sample_testing(
            current_user["username"], 
            sample_test.permit_ref, 
            sample_test.form_data, 
            is_draft=False
        )
        if success:
            return {"message": "Sample testing submitted successfully", "status": "completed"}
        result = await _save_local_sample_record(current_user["username"], sample_test.permit_ref, sample_test.form_data, False)
        if result:
            logging.info("Submitted sample testing locally because GeoProx permit was unavailable")
            return result
        raise HTTPException(status_code=404, detail="Permit not found")
    except Exception as e:
        logging.error(f"GeoProx submit sample testing error: {e}")
        result = await _save_local_sample_record(current_user["username"], sample_test.permit_ref, sample_test.form_data, False)
        if result:
            logging.info("Submitted sample testing locally due to GeoProx production error")
            return result
        raise HTTPException(status_code=500, detail="Unable to submit sample testing")

# Legacy local database routes (for backwards compatibility)
@api_router.get("/permits")
async def get_permits(search: str = "", current_user: User = Depends(get_current_user)):
    # Build search filter
    search_filter = {"created_by": current_user.id}
    if search.strip():
        search_filter["permit_number"] = {"$regex": search.strip(), "$options": "i"}
    
    permits = await db.permits.find(search_filter).to_list(1000)
    
    # Add inspection and sample status to each permit
    permits_with_status = []
    for permit in permits:
        permit_data = Permit(**permit).dict()
        
        # Check site inspections
        inspections = await db.inspections.find({"permit_id": permit["id"]}).to_list(1000)
        if inspections:
            latest_inspection = inspections[-1]
            status = latest_inspection.get("status", "pending")
            
            if status == "completed":
                permit_data["inspection_status"] = "completed"
                permit_data["inspection_results"] = {
                    "bituminous": latest_inspection.get("bituminous_result", ""),
                    "sub_base": latest_inspection.get("sub_base_result", "")
                }
            elif status == "wip":
                permit_data["inspection_status"] = "wip" 
                permit_data["inspection_results"] = {
                    "bituminous": latest_inspection.get("bituminous_result", ""),
                    "sub_base": latest_inspection.get("sub_base_result", "")
                } if latest_inspection.get("bituminous_result") else None
            else:
                permit_data["inspection_status"] = "pending"
                permit_data["inspection_results"] = None
        else:
            permit_data["inspection_status"] = "pending"
            permit_data["inspection_results"] = None
        
        # Check sample testing status
        sample_tests = await db.sample_testing.find({"permit_id": permit["id"]}).to_list(1000)
        if sample_tests:
            latest_sample = sample_tests[-1]
            sample_status = latest_sample.get("status", "pending")
            permit_data["sample_status"] = sample_status
            
            # Add sample results if completed
            if sample_status == "completed":
                sample_results = {}
                
                # Sample 1 determinants
                sample1_determinants = []
                determinants = [
                    ("Coal tar", "coal_tar_sample1", "coal_tar_conc1"),
                    ("Petroleum", "petroleum_sample1", "petroleum_conc1"),
                    ("Heavy metal", "heavy_metal_sample1", "heavy_metal_conc1"),
                    ("Asbestos", "asbestos_sample1", "asbestos_conc1"),
                    ("Other", "other_sample1", "other_conc1")
                ]
                
                for name, result_field, conc_field in determinants:
                    result_value = latest_sample.get(result_field, "")
                    conc_value = latest_sample.get(conc_field, "")
                    if result_value or conc_value:
                        sample1_determinants.append({
                            "name": name,
                            "result": result_value,
                            "concentration": conc_value
                        })
                
                if sample1_determinants:
                    sample_results["sample1_determinants"] = sample1_determinants
                
                # Sample 2 determinants
                sample2_determinants = []
                determinants2 = [
                    ("Coal tar", "coal_tar_sample2", "coal_tar_conc2"),
                    ("Petroleum", "petroleum_sample2", "petroleum_conc2"),
                    ("Heavy metal", "heavy_metal_sample2", "heavy_metal_conc2"),
                    ("Asbestos", "asbestos_sample2", "asbestos_conc2"),
                    ("Other", "other_sample2", "other_conc2")
                ]
                
                for name, result_field, conc_field in determinants2:
                    result_value = latest_sample.get(result_field, "")
                    conc_value = latest_sample.get(conc_field, "")
                    if result_value or conc_value:
                        sample2_determinants.append({
                            "name": name,
                            "result": result_value,
                            "concentration": conc_value
                        })
                
                if sample2_determinants:
                    sample_results["sample2_determinants"] = sample2_determinants
                
                if sample_results:
                    permit_data["sample_results"] = sample_results
        else:
            # Check if permit has been marked for sampling (in production this would come from desktop system)
            # For now, we'll use a field on the permit itself
            permit_data["sample_status"] = permit.get("sample_required", "not_required")
        
        permits_with_status.append(permit_data)
    
    return permits_with_status

@api_router.get("/permits/{permit_id}")
async def get_permit(permit_id: str, current_user: User = Depends(get_current_user)):
    permit = await db.permits.find_one({"id": permit_id, "created_by": current_user.id})
    if not permit:
        raise HTTPException(status_code=404, detail="Permit not found")
    
    permit_data = Permit(**permit).dict()
    
    # Check site inspections
    inspections = await db.inspections.find({"permit_id": permit_id}).to_list(1000)
    if inspections:
        latest_inspection = inspections[-1]
        status = latest_inspection.get("status", "pending")
        
        if status == "completed":
            permit_data["inspection_status"] = "completed"
            permit_data["inspection_results"] = {
                "bituminous": latest_inspection.get("bituminous_result", ""),
                "sub_base": latest_inspection.get("sub_base_result", "")
            }
        elif status == "wip":
            permit_data["inspection_status"] = "wip" 
            permit_data["inspection_results"] = {
                "bituminous": latest_inspection.get("bituminous_result", ""),
                "sub_base": latest_inspection.get("sub_base_result", "")
            } if latest_inspection.get("bituminous_result") else None
        else:
            permit_data["inspection_status"] = "pending"
            permit_data["inspection_results"] = None
    else:
        permit_data["inspection_status"] = "pending"
        permit_data["inspection_results"] = None
    
    # Check sample testing status
    sample_tests = await db.sample_testing.find({"permit_id": permit_id}).to_list(1000)
    if sample_tests:
        latest_sample = sample_tests[-1]
        sample_status = latest_sample.get("status", "pending")
        permit_data["sample_status"] = sample_status
    else:
        permit_data["sample_status"] = "not_required"  # Default to not required
    
    return permit_data

@api_router.post("/inspections/save")
async def save_inspection(inspection: InspectionCreate, current_user: User = Depends(get_current_user)):
    # Verify permit exists and belongs to user
    permit = await db.permits.find_one({"id": inspection.permit_id, "created_by": current_user.id})
    if not permit:
        raise HTTPException(status_code=404, detail="Permit not found")
    
    # Check if inspection already exists for this permit
    existing = await db.inspections.find_one({"permit_id": inspection.permit_id})
    
    inspection_data = inspection.dict()
    inspection_data["inspector_id"] = current_user.id
    inspection_data["inspection_date"] = datetime.utcnow()
    inspection_data["status"] = "wip"  # Work in progress
    
    if existing:
        # Update existing inspection
        inspection_data["id"] = existing["id"]
        await db.inspections.replace_one({"id": existing["id"]}, inspection_data)
    else:
        # Create new inspection
        inspection_data["id"] = str(uuid.uuid4())
        await db.inspections.insert_one(inspection_data)
    
    return SiteInspection(**inspection_data)

@api_router.post("/inspections/submit")
async def submit_inspection(inspection: InspectionCreate, current_user: User = Depends(get_current_user)):
    # Verify permit exists and belongs to user
    permit = await db.permits.find_one({"id": inspection.permit_id, "created_by": current_user.id})
    if not permit:
        raise HTTPException(status_code=404, detail="Permit not found")
    
    # Validate all required fields for submission
    required_fields = ['utility_type', 'q1_asbestos', 'q2_binder_shiny', 'q3_spray_pak', 
                      'q4_soil_stained', 'q5_water_moisture', 'q6_pungent_odours', 
                      'q7_litmus_paper', 'bituminous_result', 'sub_base_result']
    
    inspection_dict = inspection.dict()
    missing_fields = [field for field in required_fields if not inspection_dict.get(field)]
    
    if missing_fields:
        raise HTTPException(status_code=400, detail=f"Missing required fields: {', '.join(missing_fields)}")
    
    # Check if inspection already exists for this permit
    existing = await db.inspections.find_one({"permit_id": inspection.permit_id})
    
    inspection_data = inspection.dict()
    inspection_data["inspector_id"] = current_user.id
    inspection_data["inspection_date"] = datetime.utcnow()
    inspection_data["status"] = "completed"  # Final submission
    
    if existing:
        # Update existing inspection
        inspection_data["id"] = existing["id"]
        await db.inspections.replace_one({"id": existing["id"]}, inspection_data)
    else:
        # Create new inspection
        inspection_data["id"] = str(uuid.uuid4())
        await db.inspections.insert_one(inspection_data)
    
    return SiteInspection(**inspection_data)

@api_router.get("/inspections/{permit_id}", response_model=List[SiteInspection])
async def get_inspections(permit_id: str, current_user: User = Depends(get_current_user)):
    # Verify permit belongs to user
    permit = await db.permits.find_one({"id": permit_id, "created_by": current_user.id})
    if not permit:
        raise HTTPException(status_code=404, detail="Permit not found")
    
    inspections = await db.inspections.find({"permit_id": permit_id}).to_list(1000)
    return [SiteInspection(**inspection) for inspection in inspections]

@api_router.get("/inspections/current/{permit_id}")
async def get_current_inspection(permit_id: str, current_user: User = Depends(get_current_user)):
    # Verify permit belongs to user
    permit = await db.permits.find_one({"id": permit_id, "created_by": current_user.id})
    if not permit:
        raise HTTPException(status_code=404, detail="Permit not found")
    
    # Get the current inspection (latest one)
    inspection = await db.inspections.find_one({"permit_id": permit_id})
    if not inspection:
        return None
    
    return SiteInspection(**inspection)

# Sample Testing endpoints
@api_router.post("/sample-testing/save")
async def save_sample_testing(sample_test: SampleTestingCreate, current_user: User = Depends(get_current_user)):
    # Verify permit exists and belongs to user
    permit = await db.permits.find_one({"id": sample_test.permit_id, "created_by": current_user.id})
    if not permit:
        raise HTTPException(status_code=404, detail="Permit not found")
    
    # Check if sample test already exists for this permit
    existing = await db.sample_testing.find_one({"permit_id": sample_test.permit_id})
    
    sample_data = sample_test.dict()
    sample_data["inspector_id"] = current_user.id
    sample_data["testing_date"] = datetime.utcnow()
    sample_data["status"] = "wip"  # Work in progress
    
    if existing:
        # Update existing sample test
        sample_data["id"] = existing["id"]
        await db.sample_testing.replace_one({"id": existing["id"]}, sample_data)
    else:
        # Create new sample test
        sample_data["id"] = str(uuid.uuid4())
        await db.sample_testing.insert_one(sample_data)
    
    return SampleTesting(**sample_data)

@api_router.post("/sample-testing/submit")
async def submit_sample_testing(sample_test: SampleTestingCreate, current_user: User = Depends(get_current_user)):
    # Verify permit exists and belongs to user
    permit = await db.permits.find_one({"id": sample_test.permit_id, "created_by": current_user.id})
    if not permit:
        raise HTTPException(status_code=404, detail="Permit not found")
    
    # Check if sample test already exists for this permit
    existing = await db.sample_testing.find_one({"permit_id": sample_test.permit_id})
    
    sample_data = sample_test.dict()
    sample_data["inspector_id"] = current_user.id
    sample_data["testing_date"] = datetime.utcnow()
    sample_data["status"] = "completed"  # Final submission
    
    if existing:
        # Update existing sample test
        sample_data["id"] = existing["id"]
        await db.sample_testing.replace_one({"id": existing["id"]}, sample_data)
    else:
        # Create new sample test
        sample_data["id"] = str(uuid.uuid4())
        await db.sample_testing.insert_one(sample_data)
    
    return SampleTesting(**sample_data)

@api_router.get("/sample-testing/current/{permit_id}")
async def get_current_sample_testing(permit_id: str, current_user: User = Depends(get_current_user)):
    # Verify permit belongs to user
    permit = await db.permits.find_one({"id": permit_id, "created_by": current_user.id})
    if not permit:
        raise HTTPException(status_code=404, detail="Permit not found")
    
    # Get the current sample test (latest one)
    sample_test = await db.sample_testing.find_one({"permit_id": permit_id})
    if not sample_test:
        return None
    
    return SampleTesting(**sample_test)

@api_router.get("/")
async def api_root():
    return {"message": "GeoProx Mobile API"}


@app.get("/")
async def service_root():
    return {"status": "ok", "service": "GeoProx Mobile API"}

# Include router
app.include_router(api_router)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Startup event
@app.on_event("startup")
async def startup_db():
    try:
        await init_sample_data()
    except Exception as exc:
        logging.warning(f"Mongo init skipped due to error: {exc}")

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)
