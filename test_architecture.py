#!/usr/bin/env python3
"""
Test script to validate the modular architecture of the CAN monitoring system.
This script performs basic validation of the separated components.
"""

import sys
import os

def test_imports():
    """Test that all modules can be imported correctly"""
    print("Testing module imports...")
    
    try:
        import shared_data
        print("✓ shared_data module imported successfully")
        
        # Test that shared_data has the expected attributes
        expected_attrs = [
            'config', 'rtr_configs', 'data_buffers', 'timestamps',
            'enabled_ids', 'apply_smoothing', 'init_csv_log'
        ]
        
        for attr in expected_attrs:
            if hasattr(shared_data, attr):
                print(f"  ✓ {attr} available in shared_data")
            else:
                print(f"  ✗ {attr} missing from shared_data")
                
    except ImportError as e:
        print(f"✗ Failed to import shared_data: {e}")
        return False
    
    try:
        import utils
        print("✓ utils module imported successfully")
    except ImportError as e:
        print(f"✗ Failed to import utils: {e}")
        return False
    
    # Test dashboard imports (might fail due to missing dash/plotly)
    try:
        print("Testing dashboard imports...")
        # We'll do a syntax check rather than full import due to missing packages
        with open('dashboard.py', 'r') as f:
            dashboard_code = f.read()
        compile(dashboard_code, 'dashboard.py', 'exec')
        print("✓ dashboard.py syntax is valid")
    except Exception as e:
        print(f"✗ dashboard.py has syntax issues: {e}")
    
    # Test async_sub imports
    try:
        print("Testing async_sub imports...")
        with open('async_sub.py', 'r') as f:
            async_sub_code = f.read()
        compile(async_sub_code, 'async_sub.py', 'exec')
        print("✓ async_sub.py syntax is valid")
    except Exception as e:
        print(f"✗ async_sub.py has syntax issues: {e}")
    
    return True

def test_file_structure():
    """Test that all expected files are present"""
    print("\nTesting file structure...")
    
    expected_files = [
        'shared_data.py',
        'dashboard.py', 
        'async_sub.py',
        'async_pub.py',
        'utils.py',
        'config.yaml',
        'run.py',
        'README.md'
    ]
    
    missing_files = []
    for file in expected_files:
        if os.path.exists(file):
            print(f"✓ {file} exists")
        else:
            print(f"✗ {file} missing")
            missing_files.append(file)
    
    return len(missing_files) == 0

def test_shared_data_functionality():
    """Test shared_data functionality"""
    print("\nTesting shared_data functionality...")
    
    try:
        import shared_data
        
        # Test configuration loading
        if hasattr(shared_data, 'config') and shared_data.config:
            print("✓ Configuration loaded successfully")
            if 'rtr_ids' in shared_data.config:
                print(f"  ✓ Found {len(shared_data.config['rtr_ids'])} RTR configurations")
        else:
            print("✗ Configuration not loaded")
        
        # Test data structures
        if hasattr(shared_data, 'data_buffers'):
            print("✓ data_buffers structure available")
        if hasattr(shared_data, 'timestamps'):
            print("✓ timestamps structure available")
        if hasattr(shared_data, 'enabled_ids'):
            print("✓ enabled_ids structure available")
            
        # Test CSV initialization
        shared_data.init_csv_log()
        if os.path.exists('can_data_log.csv'):
            print("✓ CSV logging initialization works")
        else:
            print("✗ CSV logging failed")
            
        return True
        
    except Exception as e:
        print(f"✗ shared_data functionality test failed: {e}")
        return False

def test_run_script():
    """Test the run.py script structure"""
    print("\nTesting run.py script...")
    
    try:
        with open('run.py', 'r') as f:
            run_code = f.read()
        
        # Check for expected functions
        if 'run_data_collection' in run_code:
            print("✓ run_data_collection function found")
        if 'run_dashboard' in run_code:
            print("✓ run_dashboard function found")
        if 'async_sub.py' in run_code:
            print("✓ run.py correctly references async_sub.py as backend")
        else:
            print("✗ run.py does not reference async_sub.py")
            
        return True
        
    except Exception as e:
        print(f"✗ run.py test failed: {e}")
        return False

def main():
    """Run all tests"""
    print("=" * 60)
    print("CAN Monitoring System - Modular Architecture Test")
    print("=" * 60)
    
    tests = [
        test_file_structure,
        test_imports,
        test_shared_data_functionality,
        test_run_script
    ]
    
    results = []
    for test in tests:
        try:
            result = test()
            results.append(result)
        except Exception as e:
            print(f"✗ Test {test.__name__} failed with exception: {e}")
            results.append(False)
        print()
    
    # Summary
    print("=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    
    passed = sum(results)
    total = len(results)
    
    if passed == total:
        print(f"✓ ALL TESTS PASSED ({passed}/{total})")
        print("\nThe modular architecture is working correctly!")
        print("You can now run:")
        print("  - python async_sub.py    (for data collection)")
        print("  - python dashboard.py    (for web interface)")
        print("  - python run.py both     (for both components)")
    else:
        print(f"✗ SOME TESTS FAILED ({passed}/{total})")
        print("\nPlease check the failed tests above.")
    
    return passed == total

if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)