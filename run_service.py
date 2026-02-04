"""
run_service.py - Windows Service Wrapper for Spectrometer Automation
Runs as a Windows service for automatic startup and recovery.
"""

import sys
import os
import time
from pathlib import Path
import subprocess
import win32serviceutil
import win32service
import win32event
import servicemanager

class SpectrometerService(win32serviceutil.ServiceFramework):
    """Windows Service for Spectrometer Automation."""
    
    _svc_name_ = "SpectrometerAutomation"
    _svc_display_name_ = "Spectrometer Automation Service"
    _svc_description_ = "Automates spectrometer Excel report processing and Google Sheets upload"
    
    def __init__(self, args):
        win32serviceutil.ServiceFramework.__init__(self, args)
        self.hWaitStop = win32event.CreateEvent(None, 0, 0, None)
        self.is_alive = True
        
    def SvcStop(self):
        """Stop the service."""
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        self.is_alive = False
        win32event.SetEvent(self.hWaitStop)
        
    def SvcDoRun(self):
        """Main service execution."""
        servicemanager.LogMsg(
            servicemanager.EVENTLOG_INFORMATION_TYPE,
            servicemanager.PYS_SERVICE_STARTED,
            (self._svc_name_, '')
        )
        
        # Change to project directory
        os.chdir(Path(__file__).parent)
        
        # Run main.py
        self.main()
        
    def main(self):
        """Run the main automation script."""
        from core import utils
        
        logger = utils.logger
        logger.info("Windows Service starting...")
        
        # Import and run main
        from main import main as run_main
        
        # Keep restarting unless stopped
        while self.is_alive:
            try:
                run_main()
                logger.info("Main loop exited, restarting in 10 seconds...")
                time.sleep(10)
            except Exception as e:
                logger.error(f"Service crashed: {e}")
                logger.info("Restarting in 30 seconds...")
                time.sleep(30)

def install_service():
    """Install the service."""
    script_path = Path(__file__).resolve()
    win32serviceutil.InstallService(
        None,
        SpectrometerService._svc_name_,
        SpectrometerService._svc_display_name_,
        description=SpectrometerService._svc_description_,
        startType=win32service.SERVICE_AUTO_START,
        exeName=sys.executable,
        exeArgs=f'"{script_path}"'
    )
    print("Service installed. Use 'net start SpectrometerAutomation' to start.")

def uninstall_service():
    """Uninstall the service."""
    win32serviceutil.RemoveService(SpectrometerService._svc_name_)
    print("Service uninstalled.")

if __name__ == '__main__':
    if len(sys.argv) == 1:
        # Run as script
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(SpectrometerService)
        servicemanager.StartServiceCtrlDispatcher()
    else:
        # Handle command line arguments
        win32serviceutil.HandleCommandLine(SpectrometerService)