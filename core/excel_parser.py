"""
core/excel_parser.py
====================
Excel file parser for Spectrometer Automation.
Implements specific "Block-wise" extraction logic:
1. Scans Column A for Sample Name (Header Row).
2. Extracts Heat/Grade from the same row (Cols B, C).
3. Jumps exactly 8 rows down (DATA_ROW_OFFSET) to find Data.
4. Extracts Chemicals from Cols B,C,D,E,F,G,L,S.
"""

import pandas as pd
import re
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime
from collections import Counter

import config
from core import utils

# =========================================
# PRE-COMPILED REGEX
# =========================================
# Matches digits for stage code generation (e.g., "1" from "BATH-1")
RE_DIGITS = re.compile(r'\d+')
# Cleanup for chemical values (allows digits, dots, negatives, scientific notation)
RE_NON_NUMERIC = re.compile(r'[^\d\.\-eE]')

# =========================================
# DATA CLEANING
# =========================================

def _clean_chemical_value(value: Any) -> float:
    """
    Robustly converts cell values (B,C,D...) to float.
    Handles: 
    - Normal numbers (0.012)
    - Strings with commas ("0,012")
    - Trace values ("<0.001" -> 0.001)
    """
    if pd.isna(value):
        return 0.0

    str_val = str(value).strip()
    
    if str_val in config.EMPTY_VALUES:
        return 0.0

    # 1. Handle Comma Decimals (European/Legacy format)
    str_val = str_val.replace(',', '.')

    # 2. Handle Trace Indicators (e.g., "<0.001")
    # We remove non-numeric chars but keep dots and negatives
    clean_str = RE_NON_NUMERIC.sub('', str_val)

    try:
        return float(clean_str)
    except ValueError:
        return 0.0

def _clean_string_value(value: Any) -> Optional[str]:
    """Cleans metadata strings (Sample Name, Heat, Grade)."""
    if pd.isna(value):
        return None
    str_val = str(value).strip()
    return None if str_val in config.EMPTY_VALUES else str_val

def _generate_stage_code(sample_name: str) -> str:
    """
    Generates 'B1' from 'BATH-1' or 'F2' from 'FINAL-2'.
    """
    if not sample_name:
        return ""
    
    upper_name = sample_name.upper()
    
    for prefix, code in config.SAMPLE_CODE_RULES.items():
        if upper_name.startswith(prefix):
            match = RE_DIGITS.search(sample_name)
            if match:
                return f"{code}{match.group()}"
            return code # Fallback if no number found
            
    return ""

# =========================================
# BLOCK EXTRACTION LOGIC
# =========================================

def _extract_block(df: pd.DataFrame, header_row_idx: int, sample_name: str, filename: str) -> Optional[Dict]:
    """
    Extracts one complete block based on the Header Row Index.
    Logic:
    1. Header Row (N) -> Get Heat (Col B), Grade (Col C).
    2. Data Row (N + 8) -> Get Chemicals (Col B, C, D, E, F, G, L, S).
    """
    try:
        # --- 1. EXTRACT HEADER (Row N) ---
        # Column A (Stage) is already found. Now get B (Heat) and C (Grade).
        heat = _clean_string_value(df.iat[header_row_idx, config.EXCEL_COLUMNS['heat']])
        grade = _clean_string_value(df.iat[header_row_idx, config.EXCEL_COLUMNS['grade']])

        if not heat:
            utils.logger.warning(f"Skipping block at row {header_row_idx}: Missing Heat Number.")
            return None

        # Generate stage code early for BATH-1/BATH-2 check
        stage_code = _generate_stage_code(sample_name)

        # --- 2. CALCULATE DATA ROW (Row N + 8) ---
        data_row_idx = header_row_idx + config.DATA_ROW_OFFSET

        # Boundary Check
        if data_row_idx >= len(df):
            utils.logger.error(f"Block incomplete: Header at {header_row_idx}, but Data Row {data_row_idx} exceeds file.")
            return None

        # --- 3. EXTRACT CHEMICALS (Row N + 8) ---
        chemicals = {}
        has_valid_data = False
        
        # Iterate over B,C,D,E,F,G,L,S defined in config.CHEMICAL_MAP
        for elem, col_idx in config.CHEMICAL_MAP.items():
            try:
                # SPECIAL RULE: Override column S (chemical 'o') for BATH-1/BATH-2 samples
                if elem == 'o' and stage_code in ['B1', 'B2']:
                    # Set to 0.00 for BATH-1 (B1) and BATH-2 (B2) samples
                    val = 0.00
                else:
                    raw_val = df.iat[data_row_idx, col_idx]
                    val = _clean_chemical_value(raw_val)
                
                chemicals[elem] = val
                
                # Check if we have at least one non-zero number to consider this valid
                if val != 0.0:
                    has_valid_data = True
            except IndexError:
                chemicals[elem] = 0.0

        if not has_valid_data:
            utils.logger.warning(f"Skipping {sample_name}: All chemical values at row {data_row_idx} are 0.")
            return None

        # --- 4. FINALIZE RECORD ---
        # stage_code already generated above
        
        return {
            'filename': filename,
            'source_file': filename,
            'sample_name': sample_name,
            'heat_number': heat,
            'grade': grade if grade else "Unknown",
            'stage_code': stage_code,
            'gen_id': f"{heat}-{stage_code}", # Unique ID (e.g., F346-B1)
            'timestamp': datetime.now().isoformat(),
            **chemicals
        }

    except Exception as e:
        utils.logger.error(f"Error processing block for {sample_name}: {e}")
        return None

# =========================================
# MAIN PARSER
# =========================================

def parse_spectrometer_report(file_path: Path) -> List[Dict]:
    """
    Scans the Excel file block-by-block using the verified pattern.
    Includes logic to Auto-Generate FINAL-1 (F1) if missing.
    """
    if not file_path.exists():
        return []

    utils.logger.info(f"Parsing file: {file_path.name}")

    # 1. FILE STABILITY CHECK
    if not utils.wait_for_file_stable(file_path, config.FILE_STABILIZATION_TIME, config.MAX_FILE_READ_ATTEMPTS):
        utils.logger.error(f"File {file_path.name} is locked/unstable. Skipping.")
        return []

    try:
        # 2. LOAD EXCEL GRID
        df = pd.read_excel(file_path, engine='openpyxl', header=None, dtype=object)
        
        extracted_data = []
        max_rows = min(len(df), config.MAX_ROWS_TO_SCAN)
        
        empty_row_streak = 0
        MAX_EMPTY_STREAK = 50 

        # 3. SCAN LOOP - IMPROVED TO HANDLE VARIABLE NUMBER OF BLOCKS
        for r in range(max_rows):
            try:
                # Check Column A
                cell_val = df.iat[r, config.EXCEL_COLUMNS['stage']]
                sample_name = _clean_string_value(cell_val)
                
                if not sample_name:
                    empty_row_streak += 1
                    if empty_row_streak > MAX_EMPTY_STREAK:
                        utils.logger.debug(f"Stopping scan at row {r}: {MAX_EMPTY_STREAK} consecutive empty rows")
                        # Don't break, continue to scan remaining rows but log why we might stop
                        continue
                    continue
                
                # Reset empty row counter when a valid sample is found
                empty_row_streak = 0

                # Check Header
                is_header = any(sample_name.upper().startswith(p) for p in config.VALID_SAMPLE_PREFIXES)

                if is_header:
                    utils.logger.debug(f"Found Header at Row {r}: {sample_name}")
                    record = _extract_block(df, r, sample_name, file_path.name)
                    
                    if record:
                        extracted_data.append(record)
                        utils.logger.info(f"Extracted: {record['gen_id']} (Row {r} -> {r + config.DATA_ROW_OFFSET})")

            except Exception as e:
                utils.logger.debug(f"Error at row {r}: {e}")
                continue

        # =========================================================
        # IMPROVED FINAL-1 AUTO-GENERATION LOGIC
        # =========================================================
        if extracted_data:
            # Check if F1 exists in the data we just parsed
            # We look for stage_code 'F1' (which comes from FINAL-1)
            f1_exists = any(rec.get('stage_code') == 'F1' for rec in extracted_data)

            if not f1_exists:
                # IMPROVED: Determine heat number and grade from parsed data
                # Collect all heat numbers from extracted records
                heat_numbers = [rec.get('heat_number') for rec in extracted_data if rec.get('heat_number')]
                
                if not heat_numbers:
                    utils.logger.warning("Cannot auto-generate FINAL-1: No valid heat numbers found in extracted data.")
                else:
                    # Determine the correct heat number to use
                    # Count frequency of each heat number
                    heat_counter = Counter(heat_numbers)
                    
                    # Get the most common heat number
                    most_common_heat, most_common_count = heat_counter.most_common(1)[0]
                    
                    # If all records have the same heat number, use it
                    # If there are multiple different heat numbers, use the most common one
                    if len(heat_counter) > 1:
                        utils.logger.warning(f"Multiple heat numbers detected: {list(heat_counter.keys())}. Using most common: {most_common_heat}")
                    
                    # Determine grade - use the grade from the first record with the chosen heat number
                    selected_grade = "Unknown"
                    for rec in extracted_data:
                        if rec.get('heat_number') == most_common_heat:
                            grade = rec.get('grade')
                            if grade and grade != "Unknown":
                                selected_grade = grade
                                break
                    
                    # Get filename from first record
                    ref_file = extracted_data[0].get('filename')

                    utils.logger.info(f"⚠️ FINAL-1 missing for Heat {most_common_heat}. Auto-generating 0.0 record.")

                    # Create the Dummy Record
                    dummy_f1 = {
                        'filename': ref_file,
                        'source_file': ref_file,
                        'sample_name': 'FINAL-1',  # Force name
                        'heat_number': most_common_heat,   # Use determined heat
                        'grade': selected_grade,        # Use determined grade
                        'stage_code': 'F1',        # Force Code
                        'gen_id': f"{most_common_heat}-F1",# Construct ID
                        'timestamp': datetime.now().isoformat(),
                    }

                    # Set all chemical columns to 0.00 (float)
                    for chem_key in config.CHEMICAL_MAP.keys():
                        dummy_f1[chem_key] = 00.00

                    extracted_data.append(dummy_f1)
                    utils.logger.info(f"Extracted (Auto-Gen): {dummy_f1['gen_id']}")
        
        # Log summary of extracted data
        if extracted_data:
            utils.logger.info(f"Successfully extracted {len(extracted_data)} sample blocks from {file_path.name}")
            # Log the sample names for verification
            sample_names = [rec.get('sample_name') for rec in extracted_data]
            utils.logger.debug(f"Extracted samples: {sample_names}")
        else:
            utils.logger.warning(f"No valid sample blocks found in {file_path.name}")

        return extracted_data

    except Exception as e:
        utils.logger.error(f"CRITICAL parsing error {file_path.name}: {e}", exc_info=True)
        return []

# =========================================
# LOCAL TEST: VERIFY DATA FOR GOOGLE SHEETS
# =========================================
if __name__ == "__main__":
    import sys
    # Defaults to a specific test file if none provided
    test_path = Path(sys.argv[1]) if len(sys.argv) > 1 else config.MONITOR_DIR / "S-F346-001.xlsx"
    
    if test_path.exists():
        print(f"\n{'='*60}")
        print(f" TESTING PARSER ON: {test_path.name}")
        print(f"{'='*60}\n")
        
        results = parse_spectrometer_report(test_path)
        
        if not results:
            print("❌ No valid data found in file.")
        
        for i, res in enumerate(results):
            print(f" BLOCK #{i+1} DETECTED")
            print(f" {'-'*20}")
            
            # 1. Metadata (Header Row Details)
            print(f" ➤ Sample Name : {res.get('sample_name')} (Found in Col A)")
            print(f" ➤ Heat Number : {res.get('heat_number')} (Found in Col B)")
            print(f" ➤ Grade       : {res.get('grade')} (Found in Col C)")
            
            # 2. Computed Fields (For Google Sheets Logic)
            print(f" ➤ Stage Code  : {res.get('stage_code')} (Derived)")
            print(f" ➤ Generated ID: {res.get('gen_id')} (Unique Key)")
            
            # 3. Chemical Data (Data Row Details)
            print("\n ➤ Chemical Data (Extracted from Header Row + 8):")
            print(f"   [H] (Col B) : {res.get('h')}")
            print(f"   [I] (Col C) : {res.get('i')}")
            print(f"   [J] (Col D) : {res.get('j')}")
            print(f"   [K] (Col E) : {res.get('k')}")
            print(f"   [L] (Col F) : {res.get('l')}")
            print(f"   [M] (Col G) : {res.get('m')}")
            print(f"   [N] (Col L) : {res.get('n')}")
            print(f"   [O] (Col S) : {res.get('o')}")
            print(f"\n{'='*60}\n")
            
    else:
        print(f"Test file not found at: {test_path}")