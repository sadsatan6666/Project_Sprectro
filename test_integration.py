"""
test_integration.py
===================
Manual Integration Test
1. Finds a real file in 'monitor/' folder.
2. Parses it using core.excel_parser.
3. Uploads it using core.sheets_client.
"""

import sys
from pathlib import Path
import config
from core.sheets_client import GoogleSheetsClient
from core.excel_parser import parse_spectrometer_report

def run_test():
    print(f"\n{'='*60}")
    print(" 🚀 INTEGRATION TEST: LOCAL FILE -> GOOGLE SHEETS")
    print(f"{'='*60}\n")

    # 1. FIND A FILE IN MONITOR FOLDER
    # We look for any .xlsx file matching your pattern
    files = list(config.MONITOR_DIR.glob("*.xlsx"))
    
    if not files:
        print(f"❌ No Excel files found in: {config.MONITOR_DIR}")
        print("   -> Please copy a file like 'S-F346-001.xlsx' into the monitor folder first.")
        return

    test_file = files[0] # Take the first file found
    print(f"1. Found Local File: {test_file.name}")

    # 2. RUN THE PARSER
    print("2. Parsing Data...")
    parsed_data = parse_spectrometer_report(test_file)

    if not parsed_data:
        print("❌ Parser returned empty list. Check if file matches logic (BATH/FINAL rows).")
        return
    
    print(f"   ✅ Parsed {len(parsed_data)} records successfully.")
    print(f"   Sample Data: {parsed_data[0]['gen_id']} -> Heat: {parsed_data[0]['heat_number']}")

    # 3. RUN THE SHEETS CLIENT
    print("\n3. Connecting to Google Sheets...")
    try:
        client = GoogleSheetsClient()
        
        print(f"4. Uploading {len(parsed_data)} records...")
        client.upload_data(parsed_data)
        
        print(f"\n{'='*60}")
        print(" ✅ SUCCESS! Pipeline verification complete.")
        print("    Go check your Google Sheet (Copy of CHEMISTRY LOG).")
        print(f"{'='*60}\n")
        
    except Exception as e:
        print(f"\n❌ FAILED to upload: {e}")

if __name__ == "__main__":
    run_test()