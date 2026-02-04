"""
SPECTROMETER AUTOMATION CONFIGURATION
======================================
Simple, focused settings file - no business logic.
All logic belongs in core modules.
"""

from pathlib import Path

# =========================================
# 1. SYSTEM PATHS
# =========================================

BASE_DIR = Path(__file__).resolve().parent

#MONITOR_DIR = BASE_DIR / "monitor"
MONITOR_DIR = Path("C:/Users/aa/Desktop/monitor") 
BACKUP_DIR = BASE_DIR / "backup"
LOG_DIR = BASE_DIR / "logs"
PROCESSING_DIR = BASE_DIR / "processing"
ERROR_DIR = BASE_DIR / "error_files"  # <--- THIS WAS MISSING
JSON_DIR = BASE_DIR / "json"
DUPLICATES_DIR = BASE_DIR / "duplicates"  # <--- NEW: Duplicate prevention folder

CREDENTIALS_PATH = JSON_DIR / "server-de-acumelt-1f2872a3ccdb.json"

# =========================================
# 2. GOOGLE SHEETS CONFIGURATION
# =========================================

SPREADSHEET_ID = "1otC9NBNAgt4Y4WhXnnLti4hKJP90BBGVprQxyDiWyhE"
WORKSHEET_NAME = "Copy of CHEMISTRY LOG"

# Google API permissions
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

# Column indices (0-based) for Google Sheets
SHEET_COLUMNS = {
    'heat': 0,        # Column A: Heat number (F346)
    'grade': 1,       # Column B: Grade
    'gen_id': 2,      # Column C: Generated ID
    'stage_code': 6,  # Column G: Stage code (B1, F2, etc.)
    
    # Chemical value columns
    'h': 7,  # Column H
    'i': 8,  # Column I
    'j': 9,  # Column J
    'k': 10, # Column K
    'l': 11, # Column L
    'm': 12, # Column M
    'n': 13, # Column N
    'o': 14, # Column O
}

# Note: Columns D, E, F (indices 3, 4, 5) are empty and unused

# =========================================
# 3. SPECTROMETER FILE DETECTION
# =========================================

# Regex for spectrometer file names: S-F###-###.xlsx
FILENAME_PATTERN = r"^S-F\d{3}-\d{3}.*\.xlsx$"

# =========================================
# 4. EXCEL PARSING GEOMETRY
# =========================================

# Excel column positions (0-based indices)
EXCEL_COLUMNS = {
    'stage': 0,    # Column A: Sample name (BATH-1, FINAL-2)
    'heat': 1,     # Column B: Heat number
    'grade': 2,    # Column C: Grade
}

# Data row offset: Chemical values are 8 rows below sample row
DATA_ROW_OFFSET = 8

# Chemical value positions in the data row (0-based indices)
CHEMICAL_MAP = {
    'h': 1,   # Column B in data row
    'i': 2,   # Column C
    'j': 3,   # Column D
    'k': 4,   # Column E
    'l': 5,   # Column F
    'm': 6,   # Column G
    'n': 11,  # Column L (skips H-K)
    'o': 18,  # Column S (skips M-R)
}

# Safety limits
MAX_ROWS_TO_SCAN = 200

# Values to treat as empty
EMPTY_VALUES = {'', '0', '0.0', '0.00', '0.000', None}

# =========================================
# 5. SAMPLE NAME CONFIGURATION
# =========================================

# Valid sample name prefixes
VALID_SAMPLE_PREFIXES = ["BATH", "FINAL"]

# Sample name to code conversion
SAMPLE_CODE_RULES = {
    'BATH': 'B',
    'FINAL': 'F'
}

# Business rule: Prevent duplicate sample names for same heat
PREVENT_DUPLICATE_SAMPLE_NAMES = True

# =========================================
# 6. MONITORING SETTINGS
# =========================================

POLL_INTERVAL = 3              # Seconds between folder checks
FILE_STABILIZATION_TIME = 1    # Seconds to wait for file to be ready
COOLDOWN_PERIOD = 5            # Seconds to wait after processing
MAX_FILE_READ_ATTEMPTS = 10    # Attempts to read a file before giving up

# =========================================
# 7. API & RETRY SETTINGS
# =========================================

API_MAX_RETRIES = 3
API_RETRY_DELAY = 2

# =========================================
# END OF CONFIGURATION
# =========================================