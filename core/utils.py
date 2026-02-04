"""
utils.py - Shared utility functions for spectrometer automation
Handles logging, file operations, and robust stability checks.
"""

import logging
import hashlib
import time
import shutil
import os
import subprocess
import re
from datetime import datetime
from pathlib import Path
from logging.handlers import RotatingFileHandler
import config

# =========================================
# 1. LOGGING SETUP
# =========================================

def setup_logger(name="Spectrometer"):
    """Configure logging to file and console."""
    try:
        config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass # If this fails, we likely have bigger permission issues
    
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    
    if logger.hasHandlers():
        return logger
    
    log_file = config.LOG_DIR / "spectrometer.log"
    
    # File handler
    try:
        file_handler = RotatingFileHandler(
            log_file, maxBytes=5*1024*1024, backupCount=3, encoding='utf-8'
        )
        file_handler.setFormatter(logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            '%Y-%m-%d %H:%M:%S'
        ))
        logger.addHandler(file_handler)
    except Exception as e:
        print(f"CRITICAL: Could not set up file logging: {e}")

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s',
        '%H:%M:%S'
    ))
    logger.addHandler(console_handler)
    
    return logger

logger = setup_logger()

# =========================================
# 2. FILE STABILITY & CHECKING
# =========================================

def is_file_open(file_path: Path) -> bool:
    """Check if file is currently open/locked by another process."""
    if not file_path.exists():
        return False
    try:
        # Try to rename the file to itself. If locked, this usually fails on Windows.
        # Alternatively, try opening in exclusive append mode.
        with open(file_path, 'a+'):
            pass
        return False
    except (OSError, IOError, PermissionError):
        return True

def wait_for_file_stable(file_path: Path, stabilization_time: int = 2, max_attempts: int = 15) -> bool:
    """
    Blocks until file size remains constant for `stabilization_time` seconds
    and the file is not locked by the writing process.
    """
    if not file_path.exists():
        return False

    logger.debug(f"Waiting for file stability: {file_path.name}")
    
    last_size = -1
    stable_count = 0
    
    for _ in range(max_attempts):
        try:
            current_size = file_path.stat().st_size
            
            # Check if size is changing
            if current_size == last_size and current_size > 0:
                stable_count += 1
            else:
                stable_count = 0 # Reset if size changed
            
            last_size = current_size
            
            # If size is stable and file is not locked
            if stable_count >= stabilization_time:
                if not is_file_open(file_path):
                    return True
            
            time.sleep(1)
            
        except FileNotFoundError:
            return False
        except Exception as e:
            logger.warning(f"Error checking file stability: {e}")
            time.sleep(1)
            
    logger.error(f"File {file_path.name} never stabilized or unlocked.")
    return False

# =========================================
# 3. FILE OPERATIONS (MOVE/BACKUP)
# =========================================

def move_to_processing(file_path: Path) -> Path:
    """Move file to processing folder safely."""
    try:
        config.PROCESSING_DIR.mkdir(parents=True, exist_ok=True)
        dest_path = config.PROCESSING_DIR / file_path.name
        
        # If destination exists, remove it first to avoid shutil errors on some systems
        if dest_path.exists():
            dest_path.unlink()
            
        shutil.move(str(file_path), str(dest_path))
        logger.info(f"Moved to processing: {file_path.name}")
        return dest_path
    except Exception as e:
        logger.error(f"Failed to move file to processing: {e}")
        return None

def create_backup_path(file_path: Path) -> Path:
    """Generates the backup path based on Year/DayCode."""
    current_year = datetime.now().strftime("%Y")
    
    # Extract day code (e.g., F346 from S-F346-025.xlsx)
    match = re.search(r'S-F(\d{3})', file_path.name)
    day_code = f"F{match.group(1)}" if match else f"F{datetime.now().strftime('%j')}"
    
    backup_path = config.BACKUP_DIR / current_year / day_code
    backup_path.mkdir(parents=True, exist_ok=True)
    return backup_path / file_path.name

def backup_file(file_path: Path) -> bool:
    """Copy processed file to backup directory with duplicate handling."""
    try:
        backup_dest = create_backup_path(file_path)
        
        if backup_dest.exists():
            timestamp = int(time.time())
            new_name = f"DUP_{timestamp}_{backup_dest.name}"
            backup_dest = backup_dest.parent / new_name
        
        shutil.copy2(file_path, backup_dest)
        logger.info(f"Backed up to: {backup_dest}")
        
        if os.name == 'nt' and getattr(config, 'ENABLE_FILE_LOCKING', False):
            set_read_only(backup_dest)
            
        return True
    except Exception as e:
        logger.error(f"Backup failed: {e}")
        return False

def set_read_only(file_path: Path):
    """Set file to read-only (Windows only)."""
    try:
        if os.name == 'nt':
            subprocess.run(['attrib', '+R', str(file_path)], check=False)
    except Exception:
        pass

# =========================================
# 4. VALIDATION & HASHING
# =========================================

def get_file_hash(file_path: Path) -> str:
    """Calculate MD5 hash of file."""
    hash_md5 = hashlib.md5()
    try:
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()
    except Exception:
        return None