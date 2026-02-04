"""
network_utils.py - Network connectivity and resilience utilities
Handles network failures, retries, and service continuity.
"""

import socket
import urllib.request
import time
import subprocess
from typing import Optional, Tuple, Callable
from pathlib import Path
import config
from core import utils

logger = utils.logger

class NetworkError(Exception):
    """Custom exception for network-related errors."""
    pass

def check_internet_connection(timeout: int = 5) -> bool:
    """
    Check if internet connection is available.
    
    Args:
        timeout: Timeout in seconds
        
    Returns:
        True if internet is available, False otherwise
    """
    test_urls = [
        "https://www.google.com",
        "https://www.cloudflare.com",
        "https://8.8.8.8",  # Google DNS
    ]
    
    for url in test_urls:
        try:
            # Try to connect to a reliable service
            urllib.request.urlopen(url, timeout=timeout)
            logger.debug(f"Internet check passed via {url}")
            return True
        except Exception:
            continue
    
    logger.warning("No internet connectivity detected")
    return False

def check_dns_resolution(hostname: str = "oauth2.googleapis.com") -> bool:
    """
    Check if DNS resolution works for a specific hostname.
    
    Args:
        hostname: Hostname to test
        
    Returns:
        True if DNS resolution works, False otherwise
    """
    try:
        socket.gethostbyname(hostname)
        logger.debug(f"DNS resolution successful for {hostname}")
        return True
    except socket.gaierror as e:
        logger.error(f"DNS resolution failed for {hostname}: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected DNS error for {hostname}: {e}")
        return False

def wait_for_network_connection(max_wait: int = 300, check_interval: int = 10) -> bool:
    """
    Wait for network connection to become available.
    
    Args:
        max_wait: Maximum time to wait in seconds
        check_interval: Time between checks in seconds
        
    Returns:
        True if connection established, False if timeout
    """
    logger.info(f"Waiting for network connection (max {max_wait}s)...")
    
    start_time = time.time()
    attempts = 0
    
    while time.time() - start_time < max_wait:
        attempts += 1
        
        # Check internet connection
        if check_internet_connection() and check_dns_resolution():
            elapsed = time.time() - start_time
            logger.info(f"Network connection established after {elapsed:.1f}s")
            return True
        
        # Log progress every 30 seconds
        elapsed = time.time() - start_time
        if attempts % 3 == 0:  # Every 30 seconds
            logger.warning(f"Still waiting for network... ({elapsed:.0f}s elapsed)")
        
        time.sleep(check_interval)
    
    logger.error(f"Network connection timeout after {max_wait}s")
    return False

def robust_api_call(func: Callable, max_retries: int = 3, 
                   initial_delay: float = 1.0, max_delay: float = 30.0) -> any:
    """
    Execute an API call with exponential backoff and network recovery.
    
    Args:
        func: Function to call
        max_retries: Maximum retry attempts
        initial_delay: Initial delay in seconds
        max_delay: Maximum delay in seconds
        
    Returns:
        Result of the function call
        
    Raises:
        Exception: If all retries fail
    """
    delay = initial_delay
    
    for attempt in range(max_retries + 1):
        try:
            # Before each attempt, check network
            if not check_internet_connection():
                logger.warning(f"No internet on attempt {attempt + 1}, waiting...")
                if not wait_for_network_connection(max_wait=60):
                    raise NetworkError("Network unavailable")
            
            return func()
            
        except (socket.gaierror, ConnectionError, TimeoutError) as e:
            # Network-related errors
            if attempt < max_retries:
                logger.warning(
                    f"Network error on attempt {attempt + 1}/{max_retries + 1}: {e}. "
                    f"Retrying in {delay:.1f}s..."
                )
                time.sleep(delay)
                delay = min(delay * 2, max_delay)  # Exponential backoff
            else:
                logger.error(f"Network error after {max_retries + 1} attempts: {e}")
                raise
                
        except Exception as e:
            # Non-network errors
            if attempt < max_retries:
                logger.warning(
                    f"API error on attempt {attempt + 1}/{max_retries + 1}: {e}. "
                    f"Retrying in {delay:.1f}s..."
                )
                time.sleep(delay)
                delay = min(delay * 2, max_delay)
            else:
                logger.error(f"API error after {max_retries + 1} attempts: {e}")
                raise

def is_service_running(service_name: str = "SpectrometerService") -> bool:
    """
    Check if the spectrometer service is running (Windows specific).
    
    Args:
        service_name: Name of the service
        
    Returns:
        True if service is running
    """
    try:
        result = subprocess.run(
            ["sc", "query", service_name],
            capture_output=True,
            text=True,
            timeout=5
        )
        return "RUNNING" in result.stdout
    except Exception:
        return False

def schedule_service_restart(delay_minutes: int = 5) -> None:
    """
    Schedule a service restart (for Windows Task Scheduler).
    
    Args:
        delay_minutes: Delay before restart in minutes
    """
    try:
        script_path = Path(__file__).parent.parent / "main.py"
        task_name = "SpectrometerServiceRestart"
        
        # Create a scheduled task to restart the service
        command = (
            f'schtasks /create /tn "{task_name}" /tr "python {script_path}" '
            f'/sc once /st {delay_minutes} /f'
        )
        
        subprocess.run(command, shell=True, check=False)
        logger.info(f"Scheduled service restart in {delay_minutes} minutes")
    except Exception as e:
        logger.error(f"Failed to schedule restart: {e}")

def create_offline_queue() -> Path:
    """
    Create a queue for storing data when offline.
    
    Returns:
        Path to queue directory
    """
    queue_dir = config.BASE_DIR / "offline_queue"
    queue_dir.mkdir(exist_ok=True)
    return queue_dir

def save_for_offline_processing(data: list, filename: str) -> Path:
    """
    Save extracted data for processing when back online.
    
    Args:
        data: List of sample data dictionaries
        filename: Original filename
        
    Returns:
        Path to saved queue file
    """
    import json
    from datetime import datetime
    
    queue_dir = create_offline_queue()
    
    # Create unique filename with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    queue_file = queue_dir / f"{timestamp}_{filename}.json"
    
    try:
        with open(queue_file, 'w') as f:
            json.dump({
                'source_file': filename,
                'timestamp': timestamp,
                'data': data
            }, f, indent=2)
        
        logger.info(f"Saved {len(data)} samples to offline queue: {queue_file.name}")
        return queue_file
    except Exception as e:
        logger.error(f"Failed to save offline data: {e}")
        return None

def process_offline_queue() -> int:
    """
    Process any queued data from when system was offline.
    
    Returns:
        Number of queued files processed
    """
    from core.sheets_client import GoogleSheetsClient
    
    queue_dir = create_offline_queue()
    processed = 0
    
    # Get all queue files sorted by timestamp
    queue_files = sorted(queue_dir.glob("*.json"))
    
    if not queue_files:
        return 0
    
    logger.info(f"Found {len(queue_files)} files in offline queue")
    
    try:
        sheets_client = GoogleSheetsClient()
        
        for queue_file in queue_files:
            try:
                with open(queue_file, 'r') as f:
                    queue_data = json.load(f)
                
                # Upload the data
                sheets_client.upload_data(queue_data['data'])
                logger.info(f"Processed offline queue: {queue_file.name}")
                
                # Delete the queue file after successful upload
                queue_file.unlink()
                processed += 1
                
            except Exception as e:
                logger.error(f"Failed to process queue file {queue_file.name}: {e}")
                # Don't delete, will retry next time
                
    except Exception as e:
        logger.error(f"Failed to process offline queue: {e}")
    
    return processed