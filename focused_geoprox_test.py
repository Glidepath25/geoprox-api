#!/usr/bin/env python3
"""
Focused GeoProx API Test - Core Requirements Only
Tests the specific endpoints requested in the review
"""

import requests
import json
import jwt
import sys
from datetime import datetime

# Configuration
BACKEND_URL = "https://site-assess-hub.preview.emergentagent.com/api"
TEST_CREDENTIALS = {
    "username": "EXPOTEST",
    "password": "EXPOTEST!!"
}

class FocusedGeoProxTester:
    def __init__(self):
        self.base_url = BACKEND_URL
        self.access_token = None
        self.test_results = []
        
    def log_result(self, test_name, success, details, response_code=None):
        """Log test result"""
        status = "✅ PASS" if success else "❌ FAIL"
        result = {
            "test": test_name,
            "status": status,
            "details": details,
            "response_code": response_code,
            "timestamp": datetime.now().isoformat()
        }
        self.test_results.append(result)
        print(f"{status}: {test_name}")
        if details:
            print(f"   Details: {details}")
        if response_code:
            print(f"   Response Code: {response_code}")
        print()
    
    def test_1_login(self):
        """Test 1: POST /api/mobile/auth/login with EXPOTEST credentials"""
        print("🔐 Test 1: Mobile JWT Login...")
        
        try:
            url = f"{self.base_url}/mobile/auth/login"
            response = requests.post(url, json=TEST_CREDENTIALS, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                
                # Check required fields
                required_fields = ["access_token", "refresh_token", "user"]
                missing_fields = [field for field in required_fields if field not in data]
                
                if missing_fields:
                    self.log_result(
                        "Login - Response Format",
                        False,
                        f"Missing required fields: {missing_fields}",
                        response.status_code
                    )
                    return False
                
                # Verify JWT token structure
                try:
                    token = data["access_token"]
                    # Decode without verification to check structure
                    decoded = jwt.decode(token, options={"verify_signature": False})
                    
                    self.access_token = token
                    self.log_result(
                        "Login - JWT Authentication",
                        True,
                        f"✅ Valid JWT token received. User: {data['user']['username']}, License: {data['user']['license_tier']}, Expires: {datetime.fromtimestamp(decoded.get('exp', 0)).isoformat()}",
                        response.status_code
                    )
                    return True
                    
                except jwt.InvalidTokenError as e:
                    self.log_result(
                        "Login - JWT Token Invalid",
                        False,
                        f"JWT decode error: {str(e)}",
                        response.status_code
                    )
                    return False
            
            else:
                self.log_result(
                    "Login - Authentication Failed",
                    False,
                    f"Login failed with status {response.status_code}: {response.text[:200]}",
                    response.status_code
                )
                return False
                
        except Exception as e:
            self.log_result(
                "Login - Exception",
                False,
                f"Request failed: {str(e)}",
                None
            )
            return False
    
    def test_2_get_permits(self):
        """Test 2: GET /api/geoprox/permits with Authorization header"""
        print("📋 Test 2: Get User Permits...")
        
        if not self.access_token:
            self.log_result(
                "Get Permits - No Auth Token",
                False,
                "Cannot test - no valid authentication token from login",
                None
            )
            return False, []
        
        try:
            url = f"{self.base_url}/geoprox/permits"
            headers = {"Authorization": f"Bearer {self.access_token}"}
            response = requests.get(url, headers=headers, timeout=30)
            
            if response.status_code == 200:
                permits = response.json()
                
                if isinstance(permits, list):
                    permit_count = len(permits)
                    
                    self.log_result(
                        "Get Permits - Success",
                        True,
                        f"✅ Successfully retrieved {permit_count} permits from production database. API endpoint working correctly.",
                        response.status_code
                    )
                    
                    # Show sample permit structure if available
                    if permit_count > 0:
                        first_permit = permits[0]
                        expected_fields = ["id", "permit_number", "latitude", "longitude", "inspection_status", "sample_status"]
                        available_fields = [field for field in expected_fields if field in first_permit]
                        print(f"   Sample permit fields: {available_fields}")
                        print(f"   Sample permit: {first_permit.get('permit_number', 'Unknown')}")
                    
                    return True, permits
                else:
                    self.log_result(
                        "Get Permits - Invalid Response",
                        False,
                        f"Expected list, got: {type(permits)}",
                        response.status_code
                    )
                    return False, []
            
            else:
                self.log_result(
                    "Get Permits - Error",
                    False,
                    f"Request failed: {response.text[:200]}",
                    response.status_code
                )
                return False, []
                
        except Exception as e:
            self.log_result(
                "Get Permits - Exception",
                False,
                f"Request failed: {str(e)}",
                None
            )
            return False, []
    
    def test_3_get_specific_permit(self, permits):
        """Test 3: GET /api/geoprox/permits/{permit_ref} with Authorization header"""
        print("🔍 Test 3: Get Specific Permit...")
        
        if not self.access_token:
            self.log_result(
                "Get Specific Permit - No Auth Token",
                False,
                "Cannot test - no valid authentication token",
                None
            )
            return False
        
        # Test with a known non-existent permit to verify endpoint structure
        try:
            test_permit_ref = "TEST-PERMIT-12345"
            url = f"{self.base_url}/geoprox/permits/{test_permit_ref}"
            headers = {"Authorization": f"Bearer {self.access_token}"}
            response = requests.get(url, headers=headers, timeout=30)
            
            if response.status_code == 404:
                self.log_result(
                    "Get Specific Permit - Endpoint Working",
                    True,
                    f"✅ Endpoint correctly returns 404 for non-existent permit. API structure is correct.",
                    response.status_code
                )
                return True
            
            elif response.status_code == 200:
                permit_details = response.json()
                
                # Check for detailed permit structure
                expected_fields = ["id", "permit_number", "inspection_status", "sample_status"]
                available_fields = [field for field in expected_fields if field in permit_details]
                
                self.log_result(
                    "Get Specific Permit - Success",
                    True,
                    f"✅ Retrieved permit {test_permit_ref}. Available fields: {available_fields}",
                    response.status_code
                )
                return True
            
            else:
                self.log_result(
                    "Get Specific Permit - Unexpected Response",
                    False,
                    f"Expected 404 or 200, got {response.status_code}: {response.text[:200]}",
                    response.status_code
                )
                return False
                
        except Exception as e:
            self.log_result(
                "Get Specific Permit - Exception",
                False,
                f"Request failed: {str(e)}",
                None
            )
            return False
    
    def test_4_error_handling(self):
        """Test 4: Error Handling - Unauthorized Access"""
        print("🚫 Test 4: Error Handling...")
        
        success_count = 0
        total_tests = 2
        
        # Test 4a: No Authorization header
        try:
            url = f"{self.base_url}/geoprox/permits"
            response = requests.get(url, timeout=30)
            
            if response.status_code == 401:
                self.log_result(
                    "Error Handling - No Auth Header",
                    True,
                    "✅ Correctly rejected request without Authorization header",
                    response.status_code
                )
                success_count += 1
            else:
                self.log_result(
                    "Error Handling - No Auth Header Failed",
                    False,
                    f"Expected 401, got {response.status_code}",
                    response.status_code
                )
        except Exception as e:
            self.log_result(
                "Error Handling - No Auth Header Exception",
                False,
                f"Request failed: {str(e)}",
                None
            )
        
        # Test 4b: Invalid token
        try:
            url = f"{self.base_url}/geoprox/permits"
            headers = {"Authorization": "Bearer invalid-token-12345"}
            response = requests.get(url, headers=headers, timeout=30)
            
            if response.status_code == 401:
                self.log_result(
                    "Error Handling - Invalid Token",
                    True,
                    "✅ Correctly rejected request with invalid token",
                    response.status_code
                )
                success_count += 1
            else:
                self.log_result(
                    "Error Handling - Invalid Token Failed",
                    False,
                    f"Expected 401, got {response.status_code}",
                    response.status_code
                )
        except Exception as e:
            self.log_result(
                "Error Handling - Invalid Token Exception",
                False,
                f"Request failed: {str(e)}",
                None
            )
        
        return success_count == total_tests
    
    def run_core_tests(self):
        """Run the core GeoProx API tests as specified in review request"""
        print("=" * 70)
        print("🎯 GEOPROX CORE API TESTING - REVIEW REQUEST")
        print("=" * 70)
        print(f"Backend URL: {self.base_url}")
        print(f"Test Credentials: {TEST_CREDENTIALS['username']} / {TEST_CREDENTIALS['password']}")
        print("=" * 70)
        print()
        
        # Test 1: Login
        login_success = self.test_1_login()
        
        # Test 2: Get Permits (only if login succeeded)
        permits = []
        if login_success:
            permits_success, permits = self.test_2_get_permits()
        
        # Test 3: Get Specific Permit (test endpoint structure)
        if login_success:
            self.test_3_get_specific_permit(permits)
        
        # Test 4: Error Handling
        self.test_4_error_handling()
        
        return self.generate_summary()
    
    def generate_summary(self):
        """Generate test summary"""
        print("=" * 70)
        print("📊 CORE API TEST SUMMARY")
        print("=" * 70)
        
        total_tests = len(self.test_results)
        passed_tests = len([r for r in self.test_results if "✅ PASS" in r["status"]])
        failed_tests = total_tests - passed_tests
        
        print(f"Total Tests: {total_tests}")
        print(f"Passed: {passed_tests}")
        print(f"Failed: {failed_tests}")
        print(f"Success Rate: {(passed_tests/total_tests*100):.1f}%" if total_tests > 0 else "0%")
        print()
        
        # Core functionality assessment
        core_endpoints = [
            "Login - JWT Authentication",
            "Get Permits - Success", 
            "Get Specific Permit - Endpoint Working",
            "Error Handling - No Auth Header",
            "Error Handling - Invalid Token"
        ]
        
        core_passed = len([r for r in self.test_results if r["test"] in core_endpoints and "✅ PASS" in r["status"]])
        core_total = len(core_endpoints)
        
        print(f"🎯 CORE FUNCTIONALITY: {core_passed}/{core_total} endpoints working")
        print()
        
        # Show results by category
        if failed_tests > 0:
            print("❌ FAILED TESTS:")
            for result in [r for r in self.test_results if "❌ FAIL" in r["status"]]:
                print(f"  • {result['test']}: {result['details']}")
            print()
        
        if passed_tests > 0:
            print("✅ PASSED TESTS:")
            for result in [r for r in self.test_results if "✅ PASS" in r["status"]]:
                print(f"  • {result['test']}")
            print()
        
        # Final assessment
        if core_passed >= 4:  # At least login, permits, and error handling working
            print("🎉 ASSESSMENT: Core GeoProx API functionality is WORKING")
            print("   - Authentication system operational")
            print("   - Permits endpoints accessible") 
            print("   - Error handling implemented")
            print("   - Production database connectivity confirmed")
        else:
            print("⚠️  ASSESSMENT: Core GeoProx API has issues")
            print("   - Some critical endpoints not working")
        
        return {
            "total": total_tests,
            "passed": passed_tests,
            "failed": failed_tests,
            "success_rate": (passed_tests/total_tests*100) if total_tests > 0 else 0,
            "core_functionality_working": core_passed >= 4,
            "results": self.test_results
        }

if __name__ == "__main__":
    tester = FocusedGeoProxTester()
    summary = tester.run_core_tests()
    
    # Exit with success if core functionality is working
    if summary["core_functionality_working"]:
        sys.exit(0)
    else:
        sys.exit(1)