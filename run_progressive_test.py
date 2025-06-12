#!/usr/bin/env python
"""
Progressive TP Test Runner
Simple script to run the progressive TP simulation
"""

import os
import sys

def run_progressive_test():
    """Run the progressive TP simulation test"""
    print("🧪 Starting Progressive TP System Test...")
    print("="*60)
    
    # Import and run the simulator
    try:
        from progressive_tp_simulator import run_progressive_tp_simulation
        run_progressive_tp_simulation()
        
        print("\n" + "="*60)
        print("✅ Progressive TP Test Completed Successfully!")
        print("Check the output above for detailed results.")
        
    except ImportError as e:
        print(f"❌ Error importing simulator: {e}")
        print("Make sure 'progressive_tp_simulator.py' is in the same directory.")
        
    except Exception as e:
        print(f"❌ Error running test: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    run_progressive_test()