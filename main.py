"""
main.py (FIXED LOGIC)
=====================
1. Robust Network Recovery.
2. Allows re-processing of files with same name (Fixes testing issue).
3. Verbose Logging for debugging.
"""

import time
import sys
import re
import socket
import shutil
import os
from pathlib import Path
from typing import Set

# Add project root to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

import config
from core import utils
from core.excel_parser import parse_spectrometer_report
from core.sheets_client import GoogleSheetsClient

# Track files we want to IGNORE (e.g. pattern mismatch) to prevent log spam
ignored_files: Set[str] = set()

# ==========================================
# NETWORK UTILITIES
# ==========================================

def check_internet_connection(host="8.8.8.8", port=53, timeout=3):
    try:
        socket.setdefaulttimeout(timeout)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect((host, port))
        return True
    except Exception:
        return False

def wait_for_network_restoration():
    if check_internet_connection():
        return

    utils.logger.warning("⚠️ NETWORK LOST. Pausing automation...")
    
    while not check_internet_connection():
        time.sleep(5)
    
    utils.logger.info("✅ NETWORK RESTORED. Resuming scan...")

# ==========================================
# FILE RECOVERY
# ==========================================

def recover_orphaned_files():
    utils.logger.info("Checking for interrupted files in 'processing'...")
    try:
        if config.PROCESSING_DIR.exists():
            for file_path in config.PROCESSING_DIR.glob("*.xlsx"):
                if not file_path.name.startswith("~$"):
                    dest = config.MONITOR_DIR / file_path.name
                    try:
                        shutil.move(str(file_path), str(dest))
                        utils.logger.info(f"♻️ Recovered: {file_path.name}")
                    except Exception as e:
                        utils.logger.error(f"Failed to recover {file_path.name}: {e}")
    except Exception as e:
        utils.logger.error(f"Recovery Error: {e}")

# ==========================================
# PROCESSING LOGIC
# ==========================================

def validate_filename(filename: str) -> bool:
    pattern = re.compile(config.FILENAME_PATTERN)
    return bool(pattern.match(filename))

def move_to_error_folder(file_path: Path):
    try:
        config.ERROR_DIR.mkdir(parents=True, exist_ok=True)
        dest = config.ERROR_DIR / file_path.name
        if dest.exists(): os.remove(dest)
        shutil.move(str(file_path), str(dest))
        utils.logger.warning(f"❌ Moved to ERROR: {dest.name}")
    except Exception as e:
        utils.logger.error(f"Error move failed: {e}")

def process_single_file(file_path: Path):
    filename = file_path.name
    
    # 1. Validation Check
    if not validate_filename(filename):
        # Only log this ONCE per file to avoid spamming console every 3 seconds
        if filename not in ignored_files:
            utils.logger.warning(f"🚫 IGNORED (Invalid Name): {filename}")
            utils.logger.debug(f"   Expected: {config.FILENAME_PATTERN}")
            ignored_files.add(filename)
        return

    # If file matches pattern, remove from ignore list (in case it was renamed/fixed)
    if filename in ignored_files:
        ignored_files.remove(filename)

    utils.logger.info(f"--- Detected File: {filename} ---")

    # 2. Wait for Stability
    if not utils.wait_for_file_stable(file_path):
        utils.logger.error(f"Skipping {filename}: Unstable/Locked.")
        return

    # 3. Move to Processing
    processing_path = utils.move_to_processing(file_path)
    if not processing_path: return

    try:
        # 4. Parse
        try:
            extracted_data = parse_spectrometer_report(processing_path)
        except Exception as e:
            utils.logger.error(f"Parsing failed: {e}")
            move_to_error_folder(processing_path)
            return

        if not extracted_data:
            utils.logger.warning(f"No valid data. Moving to Error.")
            move_to_error_folder(processing_path)
            return

        # 5. Upload (Infinite Retry)
        upload_success = False
        while not upload_success:
            try:
                wait_for_network_restoration()
                client = GoogleSheetsClient()
                client.upload_data(extracted_data)
                upload_success = True
            except Exception as e:
                utils.logger.error(f"Upload Error: {e}")
                utils.logger.warning("Retrying in 10s...")
                time.sleep(10)
        
        # 6. Backup
        if utils.backup_file(processing_path):
            utils.logger.info(f"✓ Completed: {filename}")
        
        # 7. Cleanup
        if processing_path.exists(): 
            processing_path.unlink()
            
        # NOTE: We do NOT add to 'ignored_files' here. 
        # This allows you to paste the same filename again immediately.

    except KeyboardInterrupt:
        raise
    except Exception as e:
        utils.logger.critical(f"Critical Error: {e}", exc_info=True)
        move_to_error_folder(processing_path)

# ==========================================
# MAIN LOOP
# ==========================================

def main():
    config.MONITOR_DIR.mkdir(parents=True, exist_ok=True)
    config.PROCESSING_DIR.mkdir(parents=True, exist_ok=True)
    config.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    config.ERROR_DIR.mkdir(parents=True, exist_ok=True)

    utils.logger.info("=" * 60)
    utils.logger.info("Spectrometer Automation Service")
    utils.logger.info(f"Watching: {config.MONITOR_DIR}")
    utils.logger.info("=" * 60)

    recover_orphaned_files()

    utils.logger.info("🟢 Monitoring Active. Waiting for files...")

    while True:
        try:
            # Check Internet
            if not check_internet_connection():
                wait_for_network_restoration()

            # Scan Files
            files = sorted(config.MONITOR_DIR.glob("*.xlsx"), key=lambda f: f.stat().st_mtime)
            
            # We filter out temps (~$) but we DO NOT filter 'processed_files' anymore
            # Files are removed from monitor upon success, so any file here IS pending.
            pending_files = [f for f in files if not f.name.startswith("~$")]

            if pending_files:
                for file_path in pending_files:
                    process_single_file(file_path)
                    time.sleep(1) # Short break
            
            time.sleep(config.POLL_INTERVAL)

        except KeyboardInterrupt:
            utils.logger.info("Stopping...")
            break
        except Exception as e:
            utils.logger.error(f"Loop Crash: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()