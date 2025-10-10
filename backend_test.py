#!/usr/bin/env python3
"""
GeoProx Production Integration Backend API Tests
Tests all GeoProx production endpoints with EXPOTEST credentials
"""

import requests
import json
import sys
from datetime import datetime
from typing import Dict, Any, Optional

# Test Configuration
BASE_URL = "https://site-inspector-30.preview.emergentagent.com/api"
TEST_USERNAME = "EXPOTEST"
TEST_PASSWORD = "EXPOTEST!!"

class GeoProxAPITester:
    def __init__(self):
        self.base_url = BASE_URL
        self.token = None
        self.user_info = None
        self.test_results = []
        self.permits = []
        
    def log_result(self, test_name: str, success: bool, message: str, details: Dict = None):
        """Log test result"""
        result = {
            "test": test_name,
            "success": success,
            "message": message,
            "details": details or {},
            "timestamp": datetime.now().isoformat()
        }
        self.test_results.append(result)
        
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status}: {test_name}")
        print(f"   {message}")
        if details:
            print(f"   Details: {json.dumps(details, indent=2)}")
        print()
    
    def test_mobile_login(self) -> bool:
        """Test 1: Mobile JWT Authentication"""
        print("🔐 Testing Mobile JWT Authentication...")
        
        try:
            response = requests.post(
                f"{self.base_url}/mobile/auth/login",
                json={
                    "username": TEST_USERNAME,
                    "password": TEST_PASSWORD
                },
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                if "token" in data and "user" in data:
                    self.token = data["token"]
                    self.user_info = data["user"]
                    
                    self.log_result(
                        "Mobile JWT Login",
                        True,
                        f"Successfully authenticated user {TEST_USERNAME}",
                        {
                            "user_id": self.user_info.get("id"),
                            "username": self.user_info.get("username"),
                            "license_tier": self.user_info.get("license_tier"),
                            "is_admin": self.user_info.get("is_admin"),
                            "token_length": len(self.token)
                        }
                    )
                    return True
                else:
                    self.log_result(
                        "Mobile JWT Login",
                        False,
                        "Response missing token or user data",
                        {"response": data}
                    )
                    return False
            else:
                self.log_result(
                    "Mobile JWT Login",
                    False,
                    f"Authentication failed with status {response.status_code}",
                    {"response": response.text}
                )
                return False
                
        except Exception as e:
            self.log_result(
                "Mobile JWT Login",
                False,
                f"Authentication request failed: {str(e)}",
                {"error_type": type(e).__name__}
            )
            return False
    
    def test_get_permits(self) -> bool:
        """Test 2: Get User Permits from Production Database"""
        print("📋 Testing Get User Permits...")
        
        if not self.token:
            self.log_result("Get User Permits", False, "No authentication token available")
            return False
        
        try:
            headers = {"Authorization": f"Bearer {self.token}"}
            response = requests.get(
                f"{self.base_url}/geoprox/permits",
                headers=headers,
                timeout=30
            )
            
            if response.status_code == 200:
                permits = response.json()
                self.permits = permits
                
                if isinstance(permits, list):
                    self.log_result(
                        "Get User Permits",
                        True,
                        f"Successfully retrieved {len(permits)} permits from production database",
                        {
                            "permit_count": len(permits),
                            "sample_permits": permits[:2] if permits else [],
                            "permit_refs": [p.get("permit_number", "N/A") for p in permits[:5]]
                        }
                    )
                    return True
                else:
                    self.log_result(
                        "Get User Permits",
                        False,
                        "Response is not a list of permits",
                        {"response_type": type(permits).__name__}
                    )
                    return False
            else:
                self.log_result(
                    "Get User Permits",
                    False,
                    f"Failed to retrieve permits with status {response.status_code}",
                    {"response": response.text}
                )
                return False
                
        except Exception as e:
            self.log_result(
                "Get User Permits",
                False,
                f"Permits request failed: {str(e)}",
                {"error_type": type(e).__name__}
            )
            return False
    
    def test_get_specific_permit(self) -> bool:
        """Test 3: Get Specific Permit Details"""
        print("🔍 Testing Get Specific Permit...")
        
        if not self.token:
            self.log_result("Get Specific Permit", False, "No authentication token available")
            return False
        
        if not self.permits:
            self.log_result("Get Specific Permit", False, "No permits available for testing")
            return False
        
        try:
            # Use the first permit for testing
            test_permit = self.permits[0]
            permit_ref = test_permit.get("permit_number") or test_permit.get("id")
            
            headers = {"Authorization": f"Bearer {self.token}"}
            response = requests.get(
                f"{self.base_url}/geoprox/permits/{permit_ref}",
                headers=headers,
                timeout=30
            )
            
            if response.status_code == 200:
                permit_details = response.json()
                
                self.log_result(
                    "Get Specific Permit",
                    True,
                    f"Successfully retrieved permit details for {permit_ref}",
                    {
                        "permit_ref": permit_ref,
                        "inspection_status": permit_details.get("inspection_status"),
                        "sample_status": permit_details.get("sample_status"),
                        "proximity_risk": permit_details.get("proximity_risk_assessment"),
                        "has_inspection_results": bool(permit_details.get("inspection_results")),
                        "has_sample_results": bool(permit_details.get("sample_results"))
                    }
                )
                return True
            elif response.status_code == 404:
                self.log_result(
                    "Get Specific Permit",
                    False,
                    f"Permit {permit_ref} not found in production database",
                    {"permit_ref": permit_ref}
                )
                return False
            else:
                self.log_result(
                    "Get Specific Permit",
                    False,
                    f"Failed to retrieve permit details with status {response.status_code}",
                    {"response": response.text}
                )
                return False
                
        except Exception as e:
            self.log_result(
                "Get Specific Permit",
                False,
                f"Permit details request failed: {str(e)}",
                {"error_type": type(e).__name__}
            )
            return False
    
    def test_save_inspection_draft(self) -> bool:
        """Test 4: Save Inspection Draft"""
        print("📝 Testing Save Inspection Draft...")
        
        if not self.token:
            self.log_result("Save Inspection Draft", False, "No authentication token available")
            return False
        
        if not self.permits:
            self.log_result("Save Inspection Draft", False, "No permits available for testing")
            return False
        
        try:
            # Use the first permit for testing
            test_permit = self.permits[0]
            permit_id = test_permit.get("permit_number") or test_permit.get("id")
            
            inspection_data = {
                "permit_id": permit_id,
                "work_order_reference": "WO-TEST-001",
                "excavation_site_number": "ESN-001",
                "surface_location": "Test Location",
                "utility_type": "Gas",
                "q1_asbestos": "No",
                "q1_notes": "No asbestos detected",
                "q2_binder_shiny": "No",
                "q2_notes": "Binder appears normal",
                "q3_spray_pak": "No",
                "q3_notes": "No spray pak observed",
                "q4_soil_stained": "No",
                "q4_notes": "Soil appears clean",
                "q5_water_moisture": "No",
                "q5_notes": "Dry conditions",
                "q6_pungent_odours": "No",
                "q6_notes": "No unusual odours",
                "q7_litmus_paper": "7",
                "q7_notes": "pH neutral",
                "bituminous_result": "PASS",
                "sub_base_result": "PASS",
                "photos": []
            }
            
            headers = {"Authorization": f"Bearer {self.token}"}
            response = requests.post(
                f"{self.base_url}/geoprox/inspections/save",
                json=inspection_data,
                headers=headers,
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                
                self.log_result(
                    "Save Inspection Draft",
                    True,
                    f"Successfully saved inspection draft for permit {permit_id}",
                    {
                        "permit_id": permit_id,
                        "status": result.get("status"),
                        "message": result.get("message")
                    }
                )
                return True
            elif response.status_code == 404:
                self.log_result(
                    "Save Inspection Draft",
                    False,
                    f"Permit {permit_id} not found for inspection save",
                    {"permit_id": permit_id}
                )
                return False
            else:
                self.log_result(
                    "Save Inspection Draft",
                    False,
                    f"Failed to save inspection draft with status {response.status_code}",
                    {"response": response.text}
                )
                return False
                
        except Exception as e:
            self.log_result(
                "Save Inspection Draft",
                False,
                f"Save inspection draft request failed: {str(e)}",
                {"error_type": type(e).__name__}
            )
            return False
    
    def test_submit_inspection(self) -> bool:
        """Test 5: Submit Final Inspection"""
        print("✅ Testing Submit Final Inspection...")
        
        if not self.token:
            self.log_result("Submit Final Inspection", False, "No authentication token available")
            return False
        
        if not self.permits:
            self.log_result("Submit Final Inspection", False, "No permits available for testing")
            return False
        
        try:
            # Use the first permit for testing
            test_permit = self.permits[0]
            permit_id = test_permit.get("permit_number") or test_permit.get("id")
            
            inspection_data = {
                "permit_id": permit_id,
                "work_order_reference": "WO-TEST-002",
                "excavation_site_number": "ESN-002",
                "surface_location": "Final Test Location",
                "utility_type": "Electric",
                "q1_asbestos": "No",
                "q1_notes": "Final check - no asbestos",
                "q2_binder_shiny": "No",
                "q2_notes": "Final check - binder normal",
                "q3_spray_pak": "No",
                "q3_notes": "Final check - no spray pak",
                "q4_soil_stained": "No",
                "q4_notes": "Final check - soil clean",
                "q5_water_moisture": "No",
                "q5_notes": "Final check - dry",
                "q6_pungent_odours": "No",
                "q6_notes": "Final check - no odours",
                "q7_litmus_paper": "7",
                "q7_notes": "Final check - pH neutral",
                "bituminous_result": "PASS",
                "sub_base_result": "PASS",
                "photos": []
            }
            
            headers = {"Authorization": f"Bearer {self.token}"}
            response = requests.post(
                f"{self.base_url}/geoprox/inspections/submit",
                json=inspection_data,
                headers=headers,
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                
                self.log_result(
                    "Submit Final Inspection",
                    True,
                    f"Successfully submitted final inspection for permit {permit_id}",
                    {
                        "permit_id": permit_id,
                        "status": result.get("status"),
                        "message": result.get("message")
                    }
                )
                return True
            elif response.status_code == 404:
                self.log_result(
                    "Submit Final Inspection",
                    False,
                    f"Permit {permit_id} not found for inspection submission",
                    {"permit_id": permit_id}
                )
                return False
            else:
                self.log_result(
                    "Submit Final Inspection",
                    False,
                    f"Failed to submit final inspection with status {response.status_code}",
                    {"response": response.text}
                )
                return False
                
        except Exception as e:
            self.log_result(
                "Submit Final Inspection",
                False,
                f"Submit final inspection request failed: {str(e)}",
                {"error_type": type(e).__name__}
            )
            return False
    
    def test_save_sample_testing_draft(self) -> bool:
        """Test 6: Save Sample Testing Draft"""
        print("🧪 Testing Save Sample Testing Draft...")
        
        if not self.token:
            self.log_result("Save Sample Testing Draft", False, "No authentication token available")
            return False
        
        if not self.permits:
            self.log_result("Save Sample Testing Draft", False, "No permits available for testing")
            return False
        
        try:
            # Use the first permit for testing
            test_permit = self.permits[0]
            permit_id = test_permit.get("permit_number") or test_permit.get("id")
            
            sample_data = {
                "permit_id": permit_id,
                "sample_status": "Pending sample",
                "sampling_date": datetime.now().isoformat(),
                "results_recorded_by": "Test Inspector",
                "sampled_by": "Test Sampler",
                "notes": "Draft sample testing notes",
                "comments": "Draft testing comments",
                "sample1_number": "S1-TEST-001",
                "sample1_material": "Bituminous",
                "sample1_lab_analysis": "Pending",
                "sample2_number": "S2-TEST-001",
                "sample2_material": "Sub-base",
                "sample2_lab_analysis": "Pending",
                "coal_tar_sample1": "Not Detected",
                "coal_tar_sample2": "Not Detected",
                "petroleum_sample1": "Not Detected",
                "petroleum_sample2": "Not Detected",
                "heavy_metal_sample1": "Not Detected",
                "heavy_metal_sample2": "Not Detected",
                "asbestos_sample1": "Not Detected",
                "asbestos_sample2": "Not Detected",
                "other_sample1": "",
                "other_sample2": "",
                "coal_tar_conc1": "",
                "coal_tar_conc2": "",
                "petroleum_conc1": "",
                "petroleum_conc2": "",
                "heavy_metal_conc1": "",
                "heavy_metal_conc2": "",
                "asbestos_conc1": "",
                "asbestos_conc2": "",
                "other_conc1": "",
                "other_conc2": "",
                "field_photos": [],
                "lab_results": [],
                "general_attachments": []
            }
            
            headers = {"Authorization": f"Bearer {self.token}"}
            response = requests.post(
                f"{self.base_url}/geoprox/sample-testing/save",
                json=sample_data,
                headers=headers,
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                
                self.log_result(
                    "Save Sample Testing Draft",
                    True,
                    f"Successfully saved sample testing draft for permit {permit_id}",
                    {
                        "permit_id": permit_id,
                        "status": result.get("status"),
                        "message": result.get("message")
                    }
                )
                return True
            elif response.status_code == 404:
                self.log_result(
                    "Save Sample Testing Draft",
                    False,
                    f"Permit {permit_id} not found for sample testing save",
                    {"permit_id": permit_id}
                )
                return False
            else:
                self.log_result(
                    "Save Sample Testing Draft",
                    False,
                    f"Failed to save sample testing draft with status {response.status_code}",
                    {"response": response.text}
                )
                return False
                
        except Exception as e:
            self.log_result(
                "Save Sample Testing Draft",
                False,
                f"Save sample testing draft request failed: {str(e)}",
                {"error_type": type(e).__name__}
            )
            return False
    
    def test_submit_sample_testing(self) -> bool:
        """Test 7: Submit Final Sample Testing"""
        print("🔬 Testing Submit Final Sample Testing...")
        
        if not self.token:
            self.log_result("Submit Final Sample Testing", False, "No authentication token available")
            return False
        
        if not self.permits:
            self.log_result("Submit Final Sample Testing", False, "No permits available for testing")
            return False
        
        try:
            # Use the first permit for testing
            test_permit = self.permits[0]
            permit_id = test_permit.get("permit_number") or test_permit.get("id")
            
            sample_data = {
                "permit_id": permit_id,
                "sample_status": "Complete",
                "sampling_date": datetime.now().isoformat(),
                "results_recorded_by": "Final Test Inspector",
                "sampled_by": "Final Test Sampler",
                "notes": "Final sample testing completed",
                "comments": "All tests completed successfully",
                "sample1_number": "S1-FINAL-001",
                "sample1_material": "Bituminous",
                "sample1_lab_analysis": "Complete",
                "sample2_number": "S2-FINAL-001",
                "sample2_material": "Sub-base",
                "sample2_lab_analysis": "Complete",
                "coal_tar_sample1": "Not Detected",
                "coal_tar_sample2": "Not Detected",
                "petroleum_sample1": "Not Detected",
                "petroleum_sample2": "Not Detected",
                "heavy_metal_sample1": "Not Detected",
                "heavy_metal_sample2": "Not Detected",
                "asbestos_sample1": "Not Detected",
                "asbestos_sample2": "Not Detected",
                "other_sample1": "",
                "other_sample2": "",
                "coal_tar_conc1": "<0.1",
                "coal_tar_conc2": "<0.1",
                "petroleum_conc1": "<0.1",
                "petroleum_conc2": "<0.1",
                "heavy_metal_conc1": "<0.1",
                "heavy_metal_conc2": "<0.1",
                "asbestos_conc1": "<0.1",
                "asbestos_conc2": "<0.1",
                "other_conc1": "",
                "other_conc2": "",
                "field_photos": [],
                "lab_results": [],
                "general_attachments": []
            }
            
            headers = {"Authorization": f"Bearer {self.token}"}
            response = requests.post(
                f"{self.base_url}/geoprox/sample-testing/submit",
                json=sample_data,
                headers=headers,
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                
                self.log_result(
                    "Submit Final Sample Testing",
                    True,
                    f"Successfully submitted final sample testing for permit {permit_id}",
                    {
                        "permit_id": permit_id,
                        "status": result.get("status"),
                        "message": result.get("message")
                    }
                )
                return True
            elif response.status_code == 404:
                self.log_result(
                    "Submit Final Sample Testing",
                    False,
                    f"Permit {permit_id} not found for sample testing submission",
                    {"permit_id": permit_id}
                )
                return False
            else:
                self.log_result(
                    "Submit Final Sample Testing",
                    False,
                    f"Failed to submit final sample testing with status {response.status_code}",
                    {"response": response.text}
                )
                return False
                
        except Exception as e:
            self.log_result(
                "Submit Final Sample Testing",
                False,
                f"Submit final sample testing request failed: {str(e)}",
                {"error_type": type(e).__name__}
            )
            return False
    
    def test_error_handling(self) -> bool:
        """Test 8: Error Handling (Invalid Token, Missing Permits)"""
        print("⚠️ Testing Error Handling...")
        
        try:
            # Test with invalid token
            invalid_headers = {"Authorization": "Bearer invalid-token-12345"}
            response = requests.get(
                f"{self.base_url}/geoprox/permits",
                headers=invalid_headers,
                timeout=30
            )
            
            if response.status_code == 401:
                self.log_result(
                    "Error Handling - Invalid Token",
                    True,
                    "Correctly rejected invalid token with 401 status",
                    {"status_code": response.status_code}
                )
            else:
                self.log_result(
                    "Error Handling - Invalid Token",
                    False,
                    f"Expected 401 for invalid token, got {response.status_code}",
                    {"status_code": response.status_code}
                )
                return False
            
            # Test with missing permit
            if self.token:
                headers = {"Authorization": f"Bearer {self.token}"}
                response = requests.get(
                    f"{self.base_url}/geoprox/permits/NONEXISTENT-PERMIT-123",
                    headers=headers,
                    timeout=30
                )
                
                if response.status_code == 404:
                    self.log_result(
                        "Error Handling - Missing Permit",
                        True,
                        "Correctly returned 404 for non-existent permit",
                        {"status_code": response.status_code}
                    )
                    return True
                else:
                    self.log_result(
                        "Error Handling - Missing Permit",
                        False,
                        f"Expected 404 for missing permit, got {response.status_code}",
                        {"status_code": response.status_code}
                    )
                    return False
            
            return True
            
        except Exception as e:
            self.log_result(
                "Error Handling",
                False,
                f"Error handling test failed: {str(e)}",
                {"error_type": type(e).__name__}
            )
            return False
    
    def run_all_tests(self):
        """Run all GeoProx production integration tests"""
        print("🚀 Starting GeoProx Production Integration Tests")
        print(f"Backend URL: {self.base_url}")
        print(f"Test User: {TEST_USERNAME}")
        print("=" * 60)
        
        # Test sequence
        tests = [
            self.test_mobile_login,
            self.test_get_permits,
            self.test_get_specific_permit,
            self.test_save_inspection_draft,
            self.test_submit_inspection,
            self.test_save_sample_testing_draft,
            self.test_submit_sample_testing,
            self.test_error_handling
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
                print(f"❌ CRITICAL ERROR in {test.__name__}: {str(e)}")
                failed += 1
        
        # Summary
        print("=" * 60)
        print("🏁 TEST SUMMARY")
        print(f"✅ Passed: {passed}")
        print(f"❌ Failed: {failed}")
        print(f"📊 Success Rate: {(passed/(passed+failed)*100):.1f}%")
        
        if failed > 0:
            print("\n❌ FAILED TESTS:")
            for result in self.test_results:
                if not result["success"]:
                    print(f"   - {result['test']}: {result['message']}")
        
        print("\n📋 DETAILED RESULTS:")
        for result in self.test_results:
            status = "✅" if result["success"] else "❌"
            print(f"{status} {result['test']}: {result['message']}")
        
        return passed, failed

def main():
    """Main test execution"""
    tester = GeoProxAPITester()
    passed, failed = tester.run_all_tests()
    
    # Exit with appropriate code
    sys.exit(0 if failed == 0 else 1)

if __name__ == "__main__":
    main()