"""
Test RoleArena Server Integration

This script tests the RoleArena API endpoints to verify the integration is working.

Usage:
    python test_rolearena_server.py

Make sure the server is running:
    uvicorn server:app --reload --port 8000
"""

import requests
import json
import time

BASE_URL = "http://localhost:8000"

def print_section(title):
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)

def test_rolearena_status():
    """Test getting RoleArena status"""
    print_section("TEST 1: Get RoleArena Status (Initial)")

    response = requests.get(f"{BASE_URL}/api/rolearena/status")
    if response.status_code == 200:
        data = response.json()
        print(f"✓ Status retrieved successfully")
        print(f"  Mode: {data.get('mode', 'unknown')}")
        print(f"  Enabled: {data.get('enabled', False)}")

        if data.get('plot_state'):
            plot = data['plot_state']
            print(f"  Current Node: {plot.get('node_idx')}/{plot.get('total_nodes')} - {plot.get('current_beat')}")
            print(f"  Turns: node={plot.get('node_turns')}, total={plot.get('total_turns')}")
        return True
    else:
        print(f"✗ Failed to get status: {response.status_code}")
        return False

def test_enable_rolearena():
    """Test enabling RoleArena mode"""
    print_section("TEST 2: Enable RoleArena Mode")

    response = requests.post(
        f"{BASE_URL}/api/rolearena/toggle",
        json={"enabled": True}
    )

    if response.status_code == 200:
        data = response.json()
        print(f"✓ RoleArena mode enabled")
        print(f"  Mode: {data.get('mode')}")
        print(f"  Message: {data.get('message')}")
        time.sleep(1)  # Wait for initialization
        return True
    else:
        print(f"✗ Failed to enable: {response.status_code}")
        print(f"  Response: {response.text}")
        return False

def test_check_enabled_status():
    """Test status after enabling"""
    print_section("TEST 3: Check Status After Enabling")

    response = requests.get(f"{BASE_URL}/api/rolearena/status")
    if response.status_code == 200:
        data = response.json()
        if data.get('enabled') == True:
            print(f"✓ RoleArena is enabled")
            plot = data.get('plot_state', {})
            print(f"  Plot State:")
            print(f"    Current Node: {plot.get('node_idx')}/{plot.get('total_nodes')} - {plot.get('current_beat')}")
            print(f"    Turns: node={plot.get('node_turns')}, total={plot.get('total_turns')}")
            print(f"    Controls: {json.dumps(plot.get('director_controls', {}), indent=6)}")
            print(f"    Quality: {json.dumps(plot.get('quality_flags', {}), indent=6)}")
            return True
        else:
            print(f"✗ RoleArena not enabled")
            return False
    else:
        print(f"✗ Failed to get status: {response.status_code}")
        return False

def test_update_controls():
    """Test updating director controls"""
    print_section("TEST 4: Update Director Controls")

    new_controls = {
        "controls": {
            "pace": "fast",
            "spice": 2,
            "angst": 3,
            "comedy": 0
        }
    }

    response = requests.post(
        f"{BASE_URL}/api/rolearena/controls",
        json=new_controls
    )

    if response.status_code == 200:
        data = response.json()
        print(f"✓ Controls updated")
        print(f"  New controls: {data.get('controls')}")

        # Verify by checking status
        status_response = requests.get(f"{BASE_URL}/api/rolearena/status")
        if status_response.status_code == 200:
            status_data = status_response.json()
            plot = status_data.get('plot_state', {})
            actual_controls = plot.get('director_controls', {})
            print(f"  Verified controls: {actual_controls}")

            # Check if controls match
            for key, value in new_controls['controls'].items():
                if actual_controls.get(key) == value:
                    print(f"    ✓ {key}: {value}")
                else:
                    print(f"    ✗ {key}: expected {value}, got {actual_controls.get(key)}")
        return True
    else:
        print(f"✗ Failed to update controls: {response.status_code}")
        print(f"  Response: {response.text}")
        return False

def test_disable_rolearena():
    """Test disabling RoleArena mode"""
    print_section("TEST 5: Disable RoleArena Mode")

    response = requests.post(
        f"{BASE_URL}/api/rolearena/toggle",
        json={"enabled": False}
    )

    if response.status_code == 200:
        data = response.json()
        print(f"✓ RoleArena mode disabled")
        print(f"  Mode: {data.get('mode')}")
        print(f"  Message: {data.get('message')}")

        # Verify
        status_response = requests.get(f"{BASE_URL}/api/rolearena/status")
        if status_response.status_code == 200:
            status_data = status_response.json()
            if status_data.get('enabled') == False:
                print(f"  ✓ Verified: RoleArena is disabled")
            else:
                print(f"  ✗ Verification failed: still enabled")
        return True
    else:
        print(f"✗ Failed to disable: {response.status_code}")
        return False

def run_all_tests():
    """Run all tests"""
    print_section("ROLEARENA SERVER INTEGRATION TESTS")
    print("Make sure server is running: uvicorn server:app --reload --port 8000")

    try:
        # Test if server is reachable
        response = requests.get(f"{BASE_URL}/api/settings", timeout=2)
        if response.status_code != 200:
            print(f"\n✗ Server not responding properly at {BASE_URL}")
            print("  Start the server with: uvicorn server:app --reload --port 8000")
            return False
    except requests.exceptions.ConnectionError:
        print(f"\n✗ Cannot connect to server at {BASE_URL}")
        print("  Start the server with: uvicorn server:app --reload --port 8000")
        return False
    except Exception as e:
        print(f"\n✗ Error connecting to server: {e}")
        return False

    print(f"\n✓ Server is reachable at {BASE_URL}")

    results = []

    # Run tests in sequence
    results.append(("Initial Status", test_rolearena_status()))
    results.append(("Enable RoleArena", test_enable_rolearena()))
    results.append(("Check Enabled Status", test_check_enabled_status()))
    results.append(("Update Controls", test_update_controls()))
    results.append(("Disable RoleArena", test_disable_rolearena()))

    # Summary
    print_section("TEST SUMMARY")
    passed = sum(1 for _, result in results if result)
    total = len(results)

    for name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status}: {name}")

    print(f"\n{passed}/{total} tests passed")

    if passed == total:
        print("\n✅ ALL TESTS PASSED!")
        print("\nRoleArena is successfully integrated and ready to use.")
        print("\nNext steps:")
        print("1. Enable RoleArena: curl -X POST http://localhost:8000/api/rolearena/toggle -H 'Content-Type: application/json' -d '{\"enabled\": true}'")
        print("2. Send messages through WebSocket or frontend")
        print("3. Watch logs for [ROLEARENA] markers")
        print("4. Monitor status: curl http://localhost:8000/api/rolearena/status")
    else:
        print(f"\n⚠️  {total - passed} test(s) failed. Check the output above for details.")

    return passed == total

if __name__ == "__main__":
    import sys
    success = run_all_tests()
    sys.exit(0 if success else 1)

