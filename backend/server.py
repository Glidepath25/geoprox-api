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
    permit_id: str
    sample_status: str = "Pending sample"
    sampling_date: Optional[datetime] = None
    results_recorded_by: str = ""
    sampled_by: str = ""
    notes: str = ""
    comments: str = ""
    sample1_number: str = ""
    sample1_material: str = ""
    sample1_lab_analysis: str = ""
    sample2_number: str = ""
    sample2_material: str = ""
    sample2_lab_analysis: str = ""
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
    field_photos: List[str] = []
    lab_results: List[str] = []
    general_attachments: List[str] = []

class InspectionCreate(BaseModel):
    permit_id: str
    work_order_reference: str
    excavation_site_number: str
    surface_location: str
    utility_type: str  # User enters this on site
    q1_asbestos: str
    q1_notes: str = ""
    q2_binder_shiny: str
    q2_notes: str = ""
    q3_spray_pak: str
    q3_notes: str = ""
    q4_soil_stained: str
    q4_notes: str = ""
    q5_water_moisture: str
    q5_notes: str = ""
    q6_pungent_odours: str
    q6_notes: str = ""
    q7_litmus_paper: str
    q7_notes: str = ""
    bituminous_result: str
    sub_base_result: str
    photos: List[str] = []

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
            }
        ]
        await db.permits.insert_many(sample_permits)
        print("Sample data initialized")

# Routes
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
        else:
            permit_data["sample_status"] = "not_required"  # Default to not required
        
        permits_with_status.append(permit_data)
    
    return permits_with_status

@api_router.get("/permits/{permit_id}", response_model=Permit)
async def get_permit(permit_id: str, current_user: User = Depends(get_current_user)):
    permit = await db.permits.find_one({"id": permit_id, "created_by": current_user.id})
    if not permit:
        raise HTTPException(status_code=404, detail="Permit not found")
    return Permit(**permit)

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