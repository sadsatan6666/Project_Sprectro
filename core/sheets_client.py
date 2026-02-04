import gspread
import time
import uuid
from google.oauth2.service_account import Credentials
import config
from core import utils

class GoogleSheetsClient:
    def __init__(self):
        self.client = None
        self.sheet = None
        self.worksheet = None
        self._authenticate()

    def _authenticate(self):
        """Authenticates using the JSON file path from config."""
        try:
            utils.logger.info("Connecting to Google Sheets...")
            if not config.CREDENTIALS_PATH.exists():
                raise FileNotFoundError(f"JSON Key not found at: {config.CREDENTIALS_PATH}")

            creds = Credentials.from_service_account_file(
                config.CREDENTIALS_PATH, 
                scopes=config.SCOPES
            )
            self.client = gspread.authorize(creds)
            self.sheet = self.client.open_by_key(config.SPREADSHEET_ID)
            self.worksheet = self.sheet.worksheet(config.WORKSHEET_NAME)
            utils.logger.info(f"Connected to: {self.sheet.title} / {self.worksheet.title}")
            
        except Exception as e:
            utils.logger.error(f"Google Auth Failed: {e}")
            raise

    # ---------------------------------------------------------
    # NEW METHOD: COUNT HEAT NUMBER OCCURRENCES IN COLUMN A
    # ---------------------------------------------------------

    def count_heat_number_in_column_a(self, heat_number: str) -> int:
        """
        Counts occurrences of a given heat number in column A of Google Sheets.
        
        Args:
            heat_number: The heat number to count (e.g., 'F346')
            
        Returns:
            int: Number of occurrences (0 if not found)
        """
        for attempt in range(config.API_MAX_RETRIES):
            try:
                utils.logger.debug(f"Counting occurrences of '{heat_number}' in column A...")
                
                # Get all values from column A (excluding header row)
                column_a_values = self.worksheet.col_values(1)  # Column A is index 1 in gspread
                
                if not column_a_values:
                    utils.logger.debug("Column A is empty.")
                    return 0
                
                # Skip header row (row 1)
                values_to_check = column_a_values[1:] if len(column_a_values) > 1 else []
                
                # Count occurrences (case-insensitive, strip whitespace)
                count = 0
                for value in values_to_check:
                    if str(value).strip().upper() == str(heat_number).strip().upper():
                        count += 1
                
                utils.logger.debug(f"Found {count} occurrences of '{heat_number}' in column A.")
                return count
                
            except gspread.exceptions.APIError as e:
                if attempt < config.API_MAX_RETRIES - 1:
                    utils.logger.warning(f"API Error counting heat numbers (attempt {attempt + 1}): {e}")
                    time.sleep(config.API_RETRY_DELAY)
                    # Re-authenticate if session expired
                    self._authenticate()
                else:
                    utils.logger.error(f"Failed to count heat numbers after {config.API_MAX_RETRIES} attempts: {e}")
                    raise
            except Exception as e:
                utils.logger.error(f"Error counting heat numbers: {e}")
                if attempt < config.API_MAX_RETRIES - 1:
                    time.sleep(config.API_RETRY_DELAY)
                else:
                    raise
        
        return 0  # Should not reach here, but safe fallback

    # ---------------------------------------------------------
    # REFACTORED SECTION
    # ---------------------------------------------------------

    def _get_existing_row_map(self):
        """
        Scans Column B (Heat) and G (Stage) to build a map of existing data.
        Returns: Dict { (heat, stage): row_index }
        """
        try:
            # Fetch all values from the worksheet
            all_values = self.worksheet.get_all_values()
            
            # Create lookup dictionary for existing data
            existing_map = {}
            
            # Start from row 2 (index 1) to skip header row
            for row_idx, row in enumerate(all_values[1:], start=2):  # gspread uses 1-based indexing
                # Check if we have at least 7 columns (up to column G)
                if len(row) >= 7:
                    heat = row[1].strip()  # Column B (index 1, 0-based)
                    stage = row[6].strip()  # Column G (index 6, 0-based)
                    
                    # Only add to map if both values are non-empty
                    if heat and stage:
                        existing_map[(heat, stage)] = row_idx
                        
            utils.logger.info(f"Built existing map with {len(existing_map)} entries")
            return existing_map
            
        except Exception as e:
            utils.logger.error(f"Failed to build existing row map: {e}")
            return {}

    def _record_to_row_list(self, record, for_update=False, existing_row_index=None):
        """
        Converts a record dictionary to a row list for Google Sheets.
        
        Args:
            record: Data dictionary from parser
            for_update: If True, preserves existing unique ID in column C
            existing_row_index: Row index for updates (needed to fetch existing unique ID)
        
        Returns:
            List of cell values for the row
        """
        # Initialize row with empty strings (same length as original)
        row = [''] * 25
        
        # For updates, fetch existing unique ID from column C
        if for_update and existing_row_index:
            try:
                existing_unique_id = self.worksheet.cell(existing_row_index, 3).value  # Column C is index 3 (1-based)
                if existing_unique_id:
                    row[config.SHEET_COLUMNS['gen_id']] = existing_unique_id
                else:
                    # Fallback: generate new unique ID
                    row[config.SHEET_COLUMNS['gen_id']] = uuid.uuid4().hex[:8].lower()
            except Exception:
                row[config.SHEET_COLUMNS['gen_id']] = uuid.uuid4().hex[:8].lower()
        else:
            # For new rows, generate new unique ID
            row[config.SHEET_COLUMNS['gen_id']] = uuid.uuid4().hex[:8].lower()
        
        # Map metadata using config indices
        row[config.SHEET_COLUMNS['heat']] = record.get('heat_number', '')
        row[config.SHEET_COLUMNS['grade']] = record.get('grade', '')
        row[config.SHEET_COLUMNS['stage_code']] = record.get('stage_code', '')
        
        # Write original gen_id to column D (index 3 in 0-based, which is one column after C)
        original_gen_id_col = config.SHEET_COLUMNS['gen_id'] + 1
        row[original_gen_id_col] = record.get('gen_id', '')
        
        # Map chemicals
        for key, sheet_col_idx in config.SHEET_COLUMNS.items():
            if key in record and len(key) <= 2:  # Single letter keys for chemicals
                val = record.get(key)
                row[sheet_col_idx] = val
        
        return row

    def upload_data(self, data_list):
        """
        Main function to upload data.
        Logic: Check B & G. If exists -> Update Row. If not -> Append.
        """
        if not data_list:
            utils.logger.info("No data to upload")
            return

        try:
            # --- NEW: DUPLICATE PREVENTION CHECK ---
            # Get all unique heat numbers from incoming data
            unique_heat_numbers = set()
            for record in data_list:
                heat = record.get('heat_number', '').strip()
                if heat:  # Only add non-empty heat numbers
                    unique_heat_numbers.add(heat)
            
            # Check each unique heat number for duplicates
            for heat_number in unique_heat_numbers:
                try:
                    current_count = self.count_heat_number_in_column_a(heat_number)
                    utils.logger.info(f"Heat number '{heat_number}' currently has {current_count} entries in column A.")
                    
                    if current_count >= 4:
                        utils.logger.warning(f"❌ Duplicate detected: Heat number '{heat_number}' already has {current_count} entries in column A. Skipping upload.")
                        return  # Exit without uploading anything
                except Exception as e:
                    utils.logger.error(f"Error checking duplicates for heat number '{heat_number}': {e}")
                    # If we can't check, we should probably skip to be safe
                    utils.logger.warning(f"Skipping upload due to error checking heat number '{heat_number}'")
                    return
            
            utils.logger.info(f"✓ All heat numbers checked: {list(unique_heat_numbers)} have less than 4 entries. Proceeding with upload.")
            # --- END DUPLICATE CHECK ---

            # 1. Fetch existing state and build lookup map
            existing_map = self._get_existing_row_map()
            
            # 2. Separate incoming data into updates and appends
            update_operations = []  # List of (row_index, row_data) for batch update
            append_rows = []  # List of row_data for new rows
            
            for record in data_list:
                heat = record.get('heat_number', '')
                stage = record.get('stage_code', '')
                
                if not heat or not stage:
                    utils.logger.warning(f"Skipping record with missing heat or stage: {record}")
                    continue
                
                key = (heat, stage)
                
                if key in existing_map:
                    # Update existing row
                    row_index = existing_map[key]
                    row_data = self._record_to_row_list(record, for_update=True, existing_row_index=row_index)
                    update_operations.append((row_index, row_data))
                    utils.logger.info(f"Queued for UPDATE: {heat}-{stage} at row {row_index}")
                else:
                    # Append new row
                    row_data = self._record_to_row_list(record, for_update=False)
                    append_rows.append(row_data)
                    utils.logger.info(f"Queued for APPEND: {heat}-{stage}")
            
            # 3. Execute batch operations
            # Update existing rows first
            if update_operations:
                self._safe_batch_update(update_operations)
            
            # Append new rows
            if append_rows:
                self._safe_append(append_rows)
                
            utils.logger.info(f"Upload complete. Updated: {len(update_operations)}, Appended: {len(append_rows)}")
                
        except Exception as e:
            utils.logger.error(f"Upload flow failed: {e}")

    def _safe_append(self, rows):
        """Appends rows with Retry Logic."""
        for attempt in range(config.API_MAX_RETRIES):
            try:
                self.worksheet.append_rows(rows, value_input_option='USER_ENTERED')
                utils.logger.info(f"Successfully appended {len(rows)} rows to Google Sheets.")
                return
            except Exception as e:
                utils.logger.warning(f"API Error (Attempt {attempt+1}): {e}")
                time.sleep(config.API_RETRY_DELAY)
        
        utils.logger.error("Append failed after max retries.")

    def _safe_batch_update(self, update_operations):
        """
        Handles batch updates for existing rows.
        
        Args:
            update_operations: List of (row_index, row_data) tuples
        """
        if not update_operations:
            return
            
        # Convert to batch update format for gspread
        batch_updates = []
        
        for row_index, row_data in update_operations:
            # Create update range for the entire row
            # We update from column A (1) to the length of our row_data
            update_range = f"A{row_index}:{gspread.utils.rowcol_to_a1(row_index, len(row_data))}"
            
            # gspread expects values as list of lists (rows)
            batch_updates.append({
                'range': update_range,
                'values': [row_data]
            })
        
        # Execute batch update with retry logic
        for attempt in range(config.API_MAX_RETRIES):
            try:
                self.worksheet.batch_update(batch_updates, value_input_option='USER_ENTERED')
                utils.logger.info(f"Successfully updated {len(batch_updates)} rows in batch.")
                return
            except Exception as e:
                utils.logger.warning(f"Batch Update Error (Attempt {attempt+1}): {e}")
                time.sleep(config.API_RETRY_DELAY)
        
        utils.logger.error("Batch update failed after max retries.")

# =========================================
# SELF-TEST BLOCK
# =========================================
if __name__ == "__main__":
    print("--- Testing Google Sheets Client with Update/Append Logic ---")
    
    # 1. Initialize Client
    try:
        client = GoogleSheetsClient()
        
        # 2. Create test data with existing and new records
        timestamp = int(time.time())
        
        # Test case 1: Record that should update existing row
        update_data = [{
            'heat_number': 'F346',  # Should match existing data
            'grade': 'TEST-GRADE-UPDATED',
            'gen_id': 'F346-B1',
            'stage_code': 'B1',  # Should match existing data
            'h': 9.99,
            'i': 8.88,
            'j': 7.77,
            'l': 0.99,
            'o': 0.88
        }]
        
        # Test case 2: New record to append
        append_data = [{
            'heat_number': f'NEW-HEAT-{timestamp}',
            'grade': 'TEST-GRADE-NEW',
            'gen_id': f'NEW-HEAT-{timestamp}-B1',
            'stage_code': 'B1',
            'h': 1.11,
            'i': 2.22,
            'j': 3.33,
            'l': 0.05,
            'o': 0.01
        }]
        
        # Combine test data
        test_data = update_data + append_data
        
        print(f"Testing with {len(test_data)} records (1 update, 1 append)")
        
        # 3. Test new method: count heat number in column A
        test_heat = 'F346'
        count = client.count_heat_number_in_column_a(test_heat)
        print(f"\nTest of count_heat_number_in_column_a('{test_heat}'): {count} occurrences")
        
        # 4. Upload
        client.upload_data(test_data)
        
        print("\n✅ Test Complete. Please check your Google Sheet.")
        print("   - Updated row with Heat F346, Stage B1")
        print(f"   - Appended new row with Heat NEW-HEAT-{timestamp}")
        
    except Exception as e:
        print(f"\n❌ Test Failed: {e}")
        import traceback
        traceback.print_exc()