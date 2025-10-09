#!/usr/bin/env python3
"""
GeoProx Mobile API Backend Testing Suite
Tests authentication, permits management, and site inspections
"""

import requests
import json
import sys
from datetime import datetime

# Backend URL from frontend/.env
BASE_URL = "https://mobile-geoprox.preview.emergentagent.com/api"

class GeoProxAPITester:
    def __init__(self):
        self.base_url = BASE_URL
        self.auth_token = None
        self.test_results = []
        self.sample_permit_id = None
        
    def log_test(self, test_name, success, message, details=None):
        """Log test results"""
        result = {
            "test": test_name,
            "success": success,
            "message": message,
            "timestamp": datetime.now().isoformat(),
            "details": details
        }
        self.test_results.append(result)
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status}: {test_name} - {message}")
        if details and not success:
            print(f"   Details: {details}")
    
    def test_root_endpoint(self):
        """Test the root API endpoint"""
        try:
            response = requests.get(f"{self.base_url}/")
            if response.status_code == 200:
                data = response.json()
                if data.get("message") == "GeoProx Mobile API":
                    self.log_test("Root Endpoint", True, "API is accessible and responding correctly")
                    return True
                else:
                    self.log_test("Root Endpoint", False, f"Unexpected response: {data}")
                    return False
            else:
                self.log_test("Root Endpoint", False, f"HTTP {response.status_code}: {response.text}")
                return False
        except Exception as e:
            self.log_test("Root Endpoint", False, f"Connection error: {str(e)}")
            return False
    
    def test_login_valid_credentials(self):
        """Test login with valid credentials"""
        test_users = [
            {"username": "john.smith", "password": "password123"},
            {"username": "sarah.jones", "password": "password123"}
        ]
        
        for user in test_users:
            try:
                response = requests.post(
                    f"{self.base_url}/auth/login",
                    json=user,
                    headers={"Content-Type": "application/json"}
                )
                
                if response.status_code == 200:
                    data = response.json()
                    if "token" in data and "user" in data:
                        # Store token for first successful login
                        if not self.auth_token:
                            self.auth_token = data["token"]
                        self.log_test(f"Login - {user['username']}", True, 
                                    f"Successfully logged in user: {data['user']['username']}")
                    else:
                        self.log_test(f"Login - {user['username']}", False, 
                                    f"Missing token or user in response: {data}")
                        return False
                else:
                    self.log_test(f"Login - {user['username']}", False, 
                                f"HTTP {response.status_code}: {response.text}")
                    return False
            except Exception as e:
                self.log_test(f"Login - {user['username']}", False, f"Request error: {str(e)}")
                return False
        
        return True
    
    def test_login_invalid_credentials(self):
        """Test login with invalid credentials"""
        invalid_users = [
            {"username": "invalid.user", "password": "wrongpassword"},
            {"username": "john.smith", "password": "wrongpassword"},
            {"username": "", "password": "password123"}
        ]
        
        for user in invalid_users:
            try:
                response = requests.post(
                    f"{self.base_url}/auth/login",
                    json=user,
                    headers={"Content-Type": "application/json"}
                )
                
                if response.status_code == 401:
                    self.log_test(f"Invalid Login - {user['username'] or 'empty'}", True, 
                                "Correctly rejected invalid credentials")
                else:
                    self.log_test(f"Invalid Login - {user['username'] or 'empty'}", False, 
                                f"Expected 401, got {response.status_code}: {response.text}")
                    return False
            except Exception as e:
                self.log_test(f"Invalid Login - {user['username'] or 'empty'}", False, 
                            f"Request error: {str(e)}")
                return False
        
        return True
    
    def test_get_permits_authenticated(self):
        """Test getting permits with valid authentication"""
        if not self.auth_token:
            self.log_test("Get Permits (Auth)", False, "No auth token available")
            return False
        
        try:
            headers = {"Authorization": f"Bearer {self.auth_token}"}
            response = requests.get(f"{self.base_url}/permits", headers=headers)
            
            if response.status_code == 200:
                permits = response.json()
                if isinstance(permits, list) and len(permits) > 0:
                    # Store first permit ID for inspection tests
                    self.sample_permit_id = permits[0]["id"]
                    self.log_test("Get Permits (Auth)", True, 
                                f"Retrieved {len(permits)} permits successfully")
                    
                    # Validate permit structure
                    permit = permits[0]
                    required_fields = ["id", "permit_number", "utility_type", "works_type", 
                                     "location", "address", "highway_authority", "status"]
                    missing_fields = [field for field in required_fields if field not in permit]
                    
                    if missing_fields:
                        self.log_test("Permit Structure", False, 
                                    f"Missing required fields: {missing_fields}")
                        return False
                    else:
                        self.log_test("Permit Structure", True, "All required fields present")
                    
                    return True
                else:
                    self.log_test("Get Permits (Auth)", False, 
                                f"Expected list with permits, got: {permits}")
                    return False
            else:
                self.log_test("Get Permits (Auth)", False, 
                            f"HTTP {response.status_code}: {response.text}")
                return False
        except Exception as e:
            self.log_test("Get Permits (Auth)", False, f"Request error: {str(e)}")
            return False
    
    def test_get_permits_unauthenticated(self):
        """Test getting permits without authentication"""
        try:
            response = requests.get(f"{self.base_url}/permits")
            
            if response.status_code == 403:
                self.log_test("Get Permits (No Auth)", True, "Correctly rejected unauthenticated request")
                return True
            else:
                self.log_test("Get Permits (No Auth)", False, 
                            f"Expected 403, got {response.status_code}: {response.text}")
                return False
        except Exception as e:
            self.log_test("Get Permits (No Auth)", False, f"Request error: {str(e)}")
            return False
    
    def test_get_specific_permit(self):
        """Test getting a specific permit by ID"""
        if not self.auth_token or not self.sample_permit_id:
            self.log_test("Get Specific Permit", False, "No auth token or permit ID available")
            return False
        
        try:
            headers = {"Authorization": f"Bearer {self.auth_token}"}
            response = requests.get(f"{self.base_url}/permits/{self.sample_permit_id}", headers=headers)
            
            if response.status_code == 200:
                permit = response.json()
                if permit.get("id") == self.sample_permit_id:
                    self.log_test("Get Specific Permit", True, 
                                f"Retrieved permit {self.sample_permit_id} successfully")
                    return True
                else:
                    self.log_test("Get Specific Permit", False, 
                                f"Permit ID mismatch: expected {self.sample_permit_id}, got {permit.get('id')}")
                    return False
            else:
                self.log_test("Get Specific Permit", False, 
                            f"HTTP {response.status_code}: {response.text}")
                return False
        except Exception as e:
            self.log_test("Get Specific Permit", False, f"Request error: {str(e)}")
            return False
    
    def test_get_nonexistent_permit(self):
        """Test getting a non-existent permit"""
        if not self.auth_token:
            self.log_test("Get Nonexistent Permit", False, "No auth token available")
            return False
        
        try:
            headers = {"Authorization": f"Bearer {self.auth_token}"}
            fake_permit_id = "nonexistent-permit-id-12345"
            response = requests.get(f"{self.base_url}/permits/{fake_permit_id}", headers=headers)
            
            if response.status_code == 404:
                self.log_test("Get Nonexistent Permit", True, "Correctly returned 404 for non-existent permit")
                return True
            else:
                self.log_test("Get Nonexistent Permit", False, 
                            f"Expected 404, got {response.status_code}: {response.text}")
                return False
        except Exception as e:
            self.log_test("Get Nonexistent Permit", False, f"Request error: {str(e)}")
            return False
    
    def test_create_inspection(self):
        """Test creating a site inspection"""
        if not self.auth_token or not self.sample_permit_id:
            self.log_test("Create Inspection", False, "No auth token or permit ID available")
            return False
        
        inspection_data = {
            "permit_id": self.sample_permit_id,
            "work_order_reference": "59848",
            "excavation_site_number": "234",
            "surface_location": "Footway / Footpath",
            "q1_asbestos": "Yes",
            "q1_notes": "Test notes for asbestos check",
            "q2_binder_shiny": "Yes",
            "q2_notes": "Test notes for binder check",
            "q3_spray_pak": "Yes",
            "q3_notes": "Test notes for spray pak",
            "q4_soil_stained": "No",
            "q4_notes": "Test notes for soil staining",
            "q5_water_moisture": "No",
            "q5_notes": "Test notes for water moisture",
            "q6_pungent_odours": "No",
            "q6_notes": "Test notes for odours",
            "q7_litmus_paper": "No",
            "q7_notes": "Test notes for litmus paper",
            "bituminous_result": "Red",
            "sub_base_result": "Green",
            "photos": []
        }
        
        try:
            headers = {
                "Authorization": f"Bearer {self.auth_token}",
                "Content-Type": "application/json"
            }
            response = requests.post(f"{self.base_url}/inspections", 
                                   json=inspection_data, headers=headers)
            
            if response.status_code == 200:
                inspection = response.json()
                required_fields = ["id", "permit_id", "inspector_id", "inspection_date"]
                missing_fields = [field for field in required_fields if field not in inspection]
                
                if missing_fields:
                    self.log_test("Create Inspection", False, 
                                f"Missing required fields in response: {missing_fields}")
                    return False
                
                if inspection.get("permit_id") != self.sample_permit_id:
                    self.log_test("Create Inspection", False, 
                                f"Permit ID mismatch in response")
                    return False
                
                self.log_test("Create Inspection", True, 
                            f"Successfully created inspection with ID: {inspection['id']}")
                return True
            else:
                self.log_test("Create Inspection", False, 
                            f"HTTP {response.status_code}: {response.text}")
                return False
        except Exception as e:
            self.log_test("Create Inspection", False, f"Request error: {str(e)}")
            return False
    
    def test_create_inspection_invalid_permit(self):
        """Test creating inspection with invalid permit ID"""
        if not self.auth_token:
            self.log_test("Create Inspection (Invalid Permit)", False, "No auth token available")
            return False
        
        inspection_data = {
            "permit_id": "invalid-permit-id-12345",
            "work_order_reference": "59848",
            "excavation_site_number": "234",
            "surface_location": "Footway / Footpath",
            "q1_asbestos": "Yes",
            "q1_notes": "Test notes",
            "q2_binder_shiny": "Yes",
            "q2_notes": "Test notes",
            "q3_spray_pak": "Yes",
            "q3_notes": "Test notes",
            "q4_soil_stained": "No",
            "q4_notes": "Test notes",
            "q5_water_moisture": "No",
            "q5_notes": "Test notes",
            "q6_pungent_odours": "No",
            "q6_notes": "Test notes",
            "q7_litmus_paper": "No",
            "q7_notes": "Test notes",
            "bituminous_result": "Red",
            "sub_base_result": "Green",
            "photos": []
        }
        
        try:
            headers = {
                "Authorization": f"Bearer {self.auth_token}",
                "Content-Type": "application/json"
            }
            response = requests.post(f"{self.base_url}/inspections", 
                                   json=inspection_data, headers=headers)
            
            if response.status_code == 404:
                self.log_test("Create Inspection (Invalid Permit)", True, 
                            "Correctly rejected inspection for invalid permit")
                return True
            else:
                self.log_test("Create Inspection (Invalid Permit)", False, 
                            f"Expected 404, got {response.status_code}: {response.text}")
                return False
        except Exception as e:
            self.log_test("Create Inspection (Invalid Permit)", False, f"Request error: {str(e)}")
            return False
    
    def test_get_inspections(self):
        """Test getting inspections for a permit"""
        if not self.auth_token or not self.sample_permit_id:
            self.log_test("Get Inspections", False, "No auth token or permit ID available")
            return False
        
        try:
            headers = {"Authorization": f"Bearer {self.auth_token}"}
            response = requests.get(f"{self.base_url}/inspections/{self.sample_permit_id}", 
                                  headers=headers)
            
            if response.status_code == 200:
                inspections = response.json()
                if isinstance(inspections, list):
                    self.log_test("Get Inspections", True, 
                                f"Retrieved {len(inspections)} inspections for permit")
                    return True
                else:
                    self.log_test("Get Inspections", False, 
                                f"Expected list, got: {type(inspections)}")
                    return False
            else:
                self.log_test("Get Inspections", False, 
                            f"HTTP {response.status_code}: {response.text}")
                return False
        except Exception as e:
            self.log_test("Get Inspections", False, f"Request error: {str(e)}")
            return False
    
    def run_all_tests(self):
        """Run all tests in sequence"""
        print(f"🚀 Starting GeoProx Mobile API Backend Tests")
        print(f"📍 Testing against: {self.base_url}")
        print("=" * 60)
        
        # Test sequence
        tests = [
            self.test_root_endpoint,
            self.test_login_valid_credentials,
            self.test_login_invalid_credentials,
            self.test_get_permits_unauthenticated,
            self.test_get_permits_authenticated,
            self.test_get_specific_permit,
            self.test_get_nonexistent_permit,
            self.test_create_inspection,
            self.test_create_inspection_invalid_permit,
            self.test_get_inspections
        ]
        
        passed = 0
        failed = 0
        
        for test in tests:
            try:
                if test():
                    passed += 1
                else:
                    failed += 1
            except Exception as e:
                print(f"❌ FAIL: {test.__name__} - Unexpected error: {str(e)}")
                failed += 1
            print()  # Add spacing between tests
        
        # Summary
        print("=" * 60)
        print(f"📊 TEST SUMMARY")
        print(f"✅ Passed: {passed}")
        print(f"❌ Failed: {failed}")
        print(f"📈 Success Rate: {(passed/(passed+failed)*100):.1f}%")
        
        if failed == 0:
            print("🎉 All tests passed! Backend API is working correctly.")
            return True
        else:
            print("⚠️  Some tests failed. Check the details above.")
            return False

def main():
    """Main test runner"""
    tester = GeoProxAPITester()
    success = tester.run_all_tests()
    
    # Save detailed results to file
    with open('/app/backend_test_results.json', 'w') as f:
        json.dump(tester.test_results, f, indent=2)
    
    print(f"\n📄 Detailed results saved to: /app/backend_test_results.json")
    
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())