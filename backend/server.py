from fastapi import FastAPI, APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field
from typing import List, Optional
import uuid
from datetime import datetime
import hashlib
import jwt
from bson import ObjectId

# Import GeoProx Integration
from geoprox_integration import geoprox_auth, geoprox_permits, geoprox_db

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Create the main app
app = FastAPI()
api_router = APIRouter(prefix="/api")

# Security
security = HTTPBearer()
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

# Helper functions
def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def verify_password(password: str, hash: str) -> bool:
    return hash_password(password) == hash

def create_token(user_id: str) -> str:
    payload = {"user_id": user_id, "exp": datetime.utcnow().timestamp() + 86400}  # 24 hours
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")

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
    try:
        user = geoprox_auth.authenticate_user(user_login.username, user_login.password)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        
        token = geoprox_auth.create_jwt_token(user)
        return {
            "access_token": token,
            "refresh_token": token,  # Using same token for simplicity
            "expires_in": 86400,  # 24 hours in seconds
            "refresh_expires_in": 86400,
            "token_type": "Bearer",
            "user": {
                "id": str(user["id"]),
                "username": user["username"],
                "license_tier": user["license_tier"],
                "is_admin": user.get("is_admin", False)
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Mobile login error: {e}")
        error_msg = str(e)
        if "timeout" in error_msg.lower() or "timed out" in error_msg.lower():
            raise HTTPException(
                status_code=503, 
                detail="Production database unavailable. The GeoProx database cannot be reached. Please contact your administrator."
            )
        raise HTTPException(status_code=500, detail=f"Authentication service error: {error_msg}")

@api_router.post("/mobile/auth/refresh")
async def mobile_refresh_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Refresh JWT token"""
    try:
        new_token = geoprox_auth.refresh_token(credentials.credentials)
        if not new_token:
            raise HTTPException(status_code=401, detail="Invalid or expired token")
        
        return {"token": new_token}
    except Exception as e:
        logging.error(f"Token refresh error: {e}")
        raise HTTPException(status_code=401, detail="Token refresh failed")

async def get_current_geoprox_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Get current user from JWT token for GeoProx integration"""
    try:
        payload = geoprox_auth.verify_jwt_token(credentials.credentials)
        if not payload:
            raise HTTPException(status_code=401, detail="Invalid token")
        return payload
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
    try:
        permits = geoprox_permits.get_user_permits(current_user["username"], search)
        return permits
    except Exception as e:
        logging.error(f"GeoProx permits error: {e}")
        raise HTTPException(status_code=500, detail="Unable to fetch permits from GeoProx")

@api_router.get("/geoprox/permits/{permit_ref}")
async def get_geoprox_permit(permit_ref: str, current_user = Depends(get_current_geoprox_user)):
    """Get specific permit from production GeoProx database"""
    try:
        permit = geoprox_permits.get_permit_details(current_user["username"], permit_ref)
        if not permit:
            raise HTTPException(status_code=404, detail="Permit not found")
        return permit
    except HTTPException:
        raise  # Re-raise HTTPExceptions as-is
    except Exception as e:
        logging.error(f"GeoProx permit details error: {e}")
        raise HTTPException(status_code=500, detail="Unable to fetch permit details")

@api_router.post("/geoprox/inspections/save")
async def save_geoprox_inspection(inspection: InspectionCreate, current_user = Depends(get_current_geoprox_user)):
    """Save site inspection to production GeoProx database"""
    try:
        success = geoprox_permits.save_site_inspection(
            current_user["username"], 
            inspection.permit_ref, 
            inspection.form_data, 
            is_draft=True
        )
        if not success:
            raise HTTPException(status_code=404, detail="Permit not found")
        return {"message": "Inspection saved successfully", "status": "wip"}
    except Exception as e:
        logging.error(f"GeoProx save inspection error: {e}")
        raise HTTPException(status_code=500, detail="Unable to save inspection")

@api_router.post("/geoprox/inspections/submit")
async def submit_geoprox_inspection(inspection: InspectionCreate, current_user = Depends(get_current_geoprox_user)):
    """Submit site inspection to production GeoProx database"""
    try:
        success = geoprox_permits.save_site_inspection(
            current_user["username"], 
            inspection.permit_ref, 
            inspection.form_data, 
            is_draft=False
        )
        if not success:
            raise HTTPException(status_code=404, detail="Permit not found")
        return {"message": "Inspection submitted successfully", "status": "completed"}
    except Exception as e:
        logging.error(f"GeoProx submit inspection error: {e}")
        raise HTTPException(status_code=500, detail="Unable to submit inspection")

@api_router.post("/geoprox/sample-testing/save")
async def save_geoprox_sample_testing(sample_test: SampleTestingCreate, current_user = Depends(get_current_geoprox_user)):
    """Save sample testing to production GeoProx database"""
    try:
        success = geoprox_permits.save_sample_testing(
            current_user["username"], 
            sample_test.permit_ref, 
            sample_test.form_data, 
            is_draft=True
        )
        if not success:
            raise HTTPException(status_code=404, detail="Permit not found")
        return {"message": "Sample testing saved successfully", "status": "wip"}
    except Exception as e:
        logging.error(f"GeoProx save sample testing error: {e}")
        raise HTTPException(status_code=500, detail="Unable to save sample testing")

@api_router.post("/geoprox/sample-testing/submit")
async def submit_geoprox_sample_testing(sample_test: SampleTestingCreate, current_user = Depends(get_current_geoprox_user)):
    """Submit sample testing to production GeoProx database"""
    try:
        success = geoprox_permits.save_sample_testing(
            current_user["username"], 
            sample_test.permit_ref, 
            sample_test.form_data, 
            is_draft=False
        )
        if not success:
            raise HTTPException(status_code=404, detail="Permit not found")
        return {"message": "Sample testing submitted successfully", "status": "completed"}
    except Exception as e:
        logging.error(f"GeoProx submit sample testing error: {e}")
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
async def root():
    return {"message": "GeoProx Mobile API"}

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
    await init_sample_data()

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)