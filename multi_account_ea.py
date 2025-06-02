# --- START OF FILE multi_account_ea.py ---

import MetaTrader5 as mt5
import time
from datetime import datetime, timedelta
import logging
from logging.handlers import TimedRotatingFileHandler
import os
import json
import sys
from multiprocessing import Process
import types # types might not be needed anymore unless used dynamically elsewhere

# ------------------------------------------------------------------------
# HEARTBEAT MONITORING SYSTEM (Placed earlier for clarity)
# ------------------------------------------------------------------------

class HeartbeatMonitor:
    """
    A simple heartbeat monitoring system to track EA activity
    and detect when the EA becomes unresponsive.
    """
    def __init__(self, account_name, heartbeat_dir='heartbeats'):
        self.account_name = account_name
        self.heartbeat_dir = heartbeat_dir
        self.heartbeat_file = os.path.join(heartbeat_dir, f"{account_name}_heartbeat.txt")

        # Create heartbeat directory if it doesn't exist
        if not os.path.exists(heartbeat_dir):
            try:
                os.makedirs(heartbeat_dir)
            except OSError as e:
                # Handle potential race condition if directory is created between check and makedirs
                if not os.path.isdir(heartbeat_dir):
                    print(f"Error creating heartbeat directory {heartbeat_dir}: {e}") # Use print as logger might not be set up yet


    def update_heartbeat(self):
        """Update the heartbeat file with current timestamp"""
        try:
            current_time = datetime.now()
            with open(self.heartbeat_file, 'w') as f:
                f.write(f"Last active: {current_time.strftime('%Y-%m-%d %H:%M:%S')}")
        except Exception as e:
            # Fail silently or log if logger is available
            # print(f"Error updating heartbeat for {self.account_name}: {e}") # Optional: print error
            pass

    def get_last_heartbeat(self):
        """Get the timestamp of the last heartbeat"""
        try:
            if not os.path.exists(self.heartbeat_file):
                return None

            with open(self.heartbeat_file, 'r') as f:
                content = f.read()

            # Extract timestamp from "Last active: YYYY-MM-DD HH:MM:SS"
            timestamp_str = content.replace("Last active: ", "").strip()
            return datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
        except Exception:
            return None

    def is_stale(self, max_age_minutes=5):
        """Check if heartbeat is stale (older than max_age_minutes)"""
        last_heartbeat = self.get_last_heartbeat()
        if last_heartbeat is None:
            # If no heartbeat file exists yet, consider it potentially stale
            # This might need adjustment based on expected startup time
            return True

        current_time = datetime.now()
        age = current_time - last_heartbeat
        return age.total_seconds() / 60 > max_age_minutes


# ------------------------------------------------------------------------
# CORE PipSecureEA CLASS - Handles logic for ONE account
# ------------------------------------------------------------------------

class PipSecureEA:

    def __init__(self, account_config):
        # Account configuration
        self.account_config = account_config
        self.account_name = account_config.get('name', f"Login_{account_config.get('login', 'Unknown')}") # More robust default name
        self.TEST_MODE = account_config.get('test_mode', False)
        self.TEST_SYMBOL = account_config.get('test_symbol', 'EURUSD')

        # --- Logger setup MUST happen early ---
        # Create logger instance first
        self.logger = logging.getLogger(self.account_name)
        # Now call setup which configures this logger instance
        self.setup_logging() # Sets up self.logger
        self.tp1_hit_groups = set()  # Keep track of groups where TP1 was hit
        self.tp1_hit_file = f'logs/{self.account_name}/tp1_hit_groups.txt'
        self._load_tp1_hit_groups()  # Load saved TP1 hit groups
        # Define pip value multipliers for different currency pairs
        self.pip_multipliers = {
            'JPY': 0.01,         # For JPY pairs
            'OIL': 0.01,         # For Oil contracts
            'XAU': 0.01,         # For Gold
            'US30': 1.0,         # For Dow Jones
            'US100': 1.0,        # For Nasdaq
            'JP225': 1.0,        # For Nikkei
            'GER40': 1.0,        # For DAX
            'UK100': 1.0,        # For FTSE
            'FRA40': 1.0,        # For CAC
            'AUS200': 1.0,       # For ASX
            'ESP35': 1.0,        # For IBEX
            'EUSTX50': 1.0,      # For Euro Stoxx
            'DEFAULT': 0.0001    # For all other pairs
        }
        # Set to track positions that have already been secured
        self.secured_positions = set()
        # Dictionary to track position groups (recalculated each cycle)
        # self.position_groups = {} # No need to store long term, recalculate in check_positions
        # Parameters for grouping positions
        self.time_proximity_threshold = 5  # seconds
        self.price_proximity_threshold = 10  # pips

        # Throttled logging state
        self.last_logged = {}

        # Summary logging state
        self.last_summary_time = 0
        self.summary_counters = {
            'positions_checked': 0,
            'positions_secured': 0,
            'pending_orders_deleted': 0,
            'errors': 0,
            'tp1_secured_events': 0,
            'pending_deleted_events': 0,
            'second_price_secured_events': 0,
        }
        self.active_symbols = set() # Track symbols with positions
        # Initialize progressive TP manager
        self.progressive_tp_manager = ProgressiveTPManager(self)
        # Initialize heartbeat monitoring for this specific account instance
        self.initialize_heartbeat()




    def create_test_positions(self):
        """Create test positions that will trigger quickly"""
        if not self.TEST_MODE:
            return False
            
        self.logger.info("=== CREATING TEST POSITIONS ===")
        symbol = self.TEST_SYMBOL
        
        # Get current price
        tick = mt5.symbol_info_tick(symbol)
        if not tick:
            self.logger.error(f"Cannot get tick for {symbol}")
            return False
            
        current_price = tick.ask
        pip_size = self.get_pip_multiplier(symbol)
        
        self.logger.info(f"Current {symbol}: {current_price}, Pip size: {pip_size}")
        
        # Create positions with TPs VERY close to current price (will trigger fast)
        created_count = 0
        
        for i in range(4):
            tp_distance = (i + 1) * 3  # Only 3, 6, 9, 12 pips away!
            tp_price = current_price + (tp_distance * pip_size)
            
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": 0.01,
                "type": mt5.ORDER_TYPE_BUY,
                "price": current_price,
                "tp": tp_price,
                "sl": current_price - (30 * pip_size),
                "comment": f"TEST_TP{i+1}",
                "deviation": 20
            }
            
            # Try different filling modes (same approach as close_position method)
            filling_modes = [
                mt5.ORDER_FILLING_IOC,
                mt5.ORDER_FILLING_FOK,
                mt5.ORDER_FILLING_RETURN,
                None  # Try without filling mode as last resort
            ]
            
            position_created = False
            for filling_mode in filling_modes:
                try:
                    if filling_mode is not None:
                        request["type_filling"] = filling_mode
                    else:
                        request.pop("type_filling", None)
                    
                    self.logger.debug(f"Trying to create position {i+1} with filling mode: {filling_mode}")
                    
                    result = mt5.order_send(request)
                    
                    if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                        self.logger.info(f"✅ Created TEST position {i+1}: Ticket={result.order}, TP={tp_price}")
                        created_count += 1
                        position_created = True
                        break  # Success, exit filling mode loop
                    elif result:
                        self.logger.debug(f"Failed with filling mode {filling_mode}: {result.comment}")
                        # If it's not a filling mode error, don't try other modes
                        if "filling" not in result.comment.lower():
                            self.logger.error(f"❌ Failed to create position {i+1}: {result.comment}")
                            break
                            
                except AttributeError:
                    # This filling mode constant doesn't exist, try next one
                    continue
                except Exception as e:
                    self.logger.debug(f"Error with filling mode {filling_mode}: {str(e)}")
                    continue
            
            if not position_created:
                self.logger.error(f"❌ Failed to create position {i+1} after trying all filling modes")
                
            time.sleep(1)
        
        self.logger.info(f"=== CREATED {created_count} TEST POSITIONS ===")
        return created_count > 0

    def initialize_heartbeat(self):
        """Initialize heartbeat monitoring for this EA instance"""
        self.heartbeat = HeartbeatMonitor(self.account_name)
        self.logger.info("Heartbeat monitor initialized.")


    def setup_logging(self):
        # Create logs directory if it doesn't exist
        log_dir = f'logs/{self.account_name}'
        if not os.path.exists(log_dir):
            try:
                os.makedirs(log_dir)
            except OSError as e:
                 # Handle potential race condition if directory is created between check and makedirs
                if not os.path.isdir(log_dir):
                    print(f"Error creating log directory {log_dir}: {e}")
                    # Fallback or raise error? For now, let it proceed, logging might fail.

        # --- FIX: Clear existing handlers to prevent duplicates in tests ---
        if self.logger.hasHandlers():
            for h in self.logger.handlers[:]:
                try:
                    h.close() # Close file handles if any
                    self.logger.removeHandler(h)
                except Exception as e_close:
                     print(f"Error closing/removing handler: {e_close}")


        # --- Set up file handler with daily rotation ---
        log_file_path = f'{log_dir}/pip_secure.log'
        file_handler = None # Initialize to None
        try:
            file_handler = TimedRotatingFileHandler(
                log_file_path,
                when='midnight',
                interval=1,
                backupCount=7,  # Keep logs for 7 days
                encoding='utf-8' # Specify encoding
            )
            file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        except Exception as e:
            print(f"Error setting up file logger for {log_file_path}: {e}")
            # file_handler remains None

        # --- Set up console handler ---
        console_handler = None # Initialize to None
        try:
            # Use stdout which might handle unicode better in some terminals
            console_handler = logging.StreamHandler(stream=sys.stdout)
            console_handler.setFormatter(logging.Formatter(f'[{self.account_name}] %(asctime)s - %(levelname)s - %(message)s'))
             # Attempt to set encoding for the stream if possible (might not work on all systems)
            if hasattr(sys.stdout, 'reconfigure'):
                 try:
                     sys.stdout.reconfigure(encoding='utf-8')
                 except Exception as e_reconfigure:
                     # print(f"Note: Could not reconfigure stdout encoding: {e_reconfigure}") # Reduce noise
                     pass

        except Exception as e:
            print(f"Error setting up console logger: {e}")
            # console_handler remains None

        # --- Set logger level and add handlers ---
        self.logger.setLevel(logging.INFO) # Set desired level (INFO, DEBUG, etc.)

        # Add handlers if they were created successfully
        if file_handler:
            self.logger.addHandler(file_handler)
        if console_handler:
            self.logger.addHandler(console_handler)

        # Prevent log propagation to avoid duplicate logs if root logger is configured
        self.logger.propagate = False

        # Log initial message only if handlers were added successfully
        if self.logger.hasHandlers():
            self.logger.info(f"Logging initialized for account {self.account_name}")
        else:
            print(f"WARNING: No handlers configured for logger '{self.account_name}'. Logging will not work.")


    def log_key_event(self, event_type, message):
        """Log key events to a separate file"""
        try:
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            # Ensure logs directory exists for the key events log as well
            if not os.path.exists('logs'):
                 os.makedirs('logs')
            with open('logs/key_events.log', 'a', encoding='utf-8') as f:
                f.write(f"[{timestamp}] [{self.account_name}] [{event_type}] {message}\n")
        except Exception as e:
            self.logger.error(f"Error writing to key events log: {str(e)}")


    # --- Methods moved inside the class ---
    def log_throttled(self, level, message, key=None, interval=300):
        """Log a message only if it hasn't been logged in the last [interval] seconds"""
        current_time = time.time()
        log_key = key or message

        # Only log if we haven't logged this message recently
        if log_key not in self.last_logged or (current_time - self.last_logged.get(log_key, 0)) > interval:
            log_func = getattr(self.logger, level.lower(), self.logger.info) # Get logger method
            log_func(message)

            # Update last logged time for this message
            self.last_logged[log_key] = current_time

    def log_summary(self, force=False):
        """Log a summary of current activity"""
        current_time = time.time()

        # Log summary every 5 minutes or when forced
        if force or (current_time - self.last_summary_time) > 300:
            active_symbols_str = ", ".join(sorted(list(self.active_symbols))) if self.active_symbols else "None"

            self.logger.info("==== ACTIVITY SUMMARY ====")
            self.logger.info(f"Positions checked: {self.summary_counters['positions_checked']}")
            self.logger.info(f"Positions secured (Total): {self.summary_counters['positions_secured']}")
            self.logger.info(f"  - TP1 secured events: {self.summary_counters['tp1_secured_events']}")
            self.logger.info(f"  - 2nd Price secured events: {self.summary_counters['second_price_secured_events']}")
            self.logger.info(f"Pending orders deleted: {self.summary_counters['pending_orders_deleted']}")
            self.logger.info(f"  - Pending deleted events: {self.summary_counters['pending_deleted_events']}")
            self.logger.info(f"Errors encountered: {self.summary_counters['errors']}")
            self.logger.info(f"Active symbols: {active_symbols_str}")
            self.logger.info("=========================")

            # Reset counters (keep total secured for info)
            self.summary_counters['positions_checked'] = 0
            # self.summary_counters['positions_secured'] = 0 # Keep total count
            self.summary_counters['pending_orders_deleted'] = 0
            self.summary_counters['errors'] = 0
            self.summary_counters['tp1_secured_events'] = 0
            self.summary_counters['pending_deleted_events'] = 0
            self.summary_counters['second_price_secured_events'] = 0
            self.active_symbols.clear() # Clear active symbols for the next interval

            # Update last summary time
            self.last_summary_time = current_time
            
    #save/load TP1 hit groups:
    def _load_tp1_hit_groups(self):
        """Load saved TP1 hit groups from file"""
        try:
            if os.path.exists(self.tp1_hit_file):
                with open(self.tp1_hit_file, 'r') as f:
                    for line in f:
                        self.tp1_hit_groups.add(line.strip())
                
                # Use safer logging
                if hasattr(self, 'logger'):
                    self.logger.info(f"Loaded {len(self.tp1_hit_groups)} TP1 hit groups from file")
                else:
                    print(f"Loaded {len(self.tp1_hit_groups)} TP1 hit groups from file")
        except Exception as e:
            # Use safer error logging
            if hasattr(self, 'logger'):
                self.logger.error(f"Error loading TP1 hit groups: {str(e)}")
            else:
                print(f"Error loading TP1 hit groups: {str(e)}")

    def _save_tp1_hit_group(self, group_id):
        """Save a group_id to the TP1 hit groups file"""
        try:
            if group_id not in self.tp1_hit_groups:
                self.tp1_hit_groups.add(group_id)
                with open(self.tp1_hit_file, 'a') as f:
                    f.write(f"{group_id}\n")
                self.logger.info(f"Saved group {group_id} to TP1 hit groups file")
        except Exception as e:
            self.logger.error(f"Error saving TP1 hit group: {str(e)}")

    def should_evaluate_tp_conditions(self, group, current_price):
        """
        Determine if TP conditions should be evaluated for a position group.
        
        In real trading: Position existence means entry was already validated by broker.
        For simulation: We need to validate entry logic based on order type.
        """
        if not group:
            return False
            
        sample_position = group[0]
        entry_price = sample_position.price_open
        
        # Check if this is a test/simulation environment
        if self.TEST_MODE:
            # In test mode, use stricter entry validation for simulation accuracy
            if sample_position.type == mt5.ORDER_TYPE_SELL:
                # For SELL: Position should exist if price ever went above entry
                # But since we're testing, we assume positions exist if they're in our test data
                self.logger.debug(f"TEST MODE: SELL position {sample_position.ticket} - assuming entry was valid")
                return True
            else:
                # For BUY: Similar logic for test mode
                self.logger.debug(f"TEST MODE: BUY position {sample_position.ticket} - assuming entry was valid")
                return True
        
        # REAL TRADING LOGIC:
        # If position exists in MT5, the broker already validated entry conditions
        # We don't need to re-validate entry because:
        # 1. LIMIT orders only execute when price reaches the limit level
        # 2. MARKET orders execute immediately at current price
        # 3. Position existence = successful entry execution
        
        self.logger.debug(f"LIVE MODE: Position {sample_position.ticket} exists - entry was valid")
        return True


    def connect(self):
        # Initialize connection to MetaTrader 5
        self.logger.info(f"Attempting to connect to account {self.account_name}...")
        init_success = mt5.initialize(
            path=self.account_config.get('terminal_path', None),
            login=self.account_config.get('login'),
            password=self.account_config.get('password'),
            server=self.account_config.get('server'),
            timeout=30000 # Add timeout (milliseconds)
        )

        if not init_success:
            error_code = mt5.last_error()
            self.logger.error(f"MT5 initialization failed for account {self.account_name}. Error code: {error_code}")
            self.summary_counters['errors'] += 1
            return False

        account_info = mt5.account_info()
        if account_info is None:
             error_code = mt5.last_error()
             self.logger.error(f"Failed to get account info after MT5 initialization for {self.account_name}. Error: {error_code}")
             mt5.shutdown()
             self.summary_counters['errors'] += 1
             return False


        self.logger.info(f"Connected to MT5 account {self.account_name} (Login: {account_info.login}, Server: {account_info.server}) successfully")

        # Update heartbeat on successful connection
        self.heartbeat.update_heartbeat()
        return True

    def disconnect(self):
        # Shut down connection to MetaTrader 5
        mt5.shutdown()
        self.logger.info(f"Disconnected from MT5 account {self.account_name}")

    def get_pip_multiplier(self, symbol):
        # Return appropriate pip multiplier based on currency pair or instrument type
        # Check specific prefixes first
        if 'GOLD' in symbol.upper():
             return 0.01  # Use 0.01 for GOLD instead of 0.0001
        for prefix, multiplier in self.pip_multipliers.items():
             if prefix != 'DEFAULT' and symbol.startswith(prefix):
                 return multiplier
        # Check for JPY suffix
        if 'JPY' in symbol.upper():
             return self.pip_multipliers['JPY']

        # Fallback to default
        return self.pip_multipliers['DEFAULT']

    def secure_position(self, position, log_as_tp1_hit=False):
        # Check if stop loss is already at entry price (with small threshold for floating point comparison)
        # Get symbol info for digits
        symbol_info = mt5.symbol_info(position.symbol)
        if not symbol_info:
            self.logger.warning(f"Could not get symbol info for {position.symbol} to check SL precision.")
            sl_threshold = 0.00001 # Default small threshold
        else:
            sl_threshold = 10**(-symbol_info.digits) # Threshold based on symbol precision

        if abs(position.sl - position.price_open) < sl_threshold:
            self.log_throttled('info', f"Position {position.ticket} already secured at entry.", key=f"secured_{position.ticket}")
            if position.ticket not in self.secured_positions:
                 self.secured_positions.add(position.ticket) # Ensure it's marked if somehow missed
            return True # Already secured

        self.logger.info(f"[TARGET] Securing position {position.ticket} ({position.symbol}) at entry price {position.price_open}")
        self.logger.info(f"  Type: {'BUY' if position.type == mt5.ORDER_TYPE_BUY else 'SELL'}, Volume: {position.volume}, Current SL: {position.sl}")

        # Verify position still exists before modification
        position_check = mt5.positions_get(ticket=position.ticket)
        if not position_check:
            self.logger.error(f"Position {position.ticket} no longer exists, cannot secure.")
            self.summary_counters['errors'] += 1
            # Remove from secured set if it was there erroneously
            if position.ticket in self.secured_positions:
                self.secured_positions.remove(position.ticket)
            return False

        # Check if SL=entry is a valid price (e.g., not too close to market for some brokers)
        # This check is complex and broker-specific, we'll rely on order_send result for now.

        # Create request with stop loss and potentially preserve take profit
        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "position": position.ticket,
            "symbol": position.symbol,
            "sl": position.price_open,  # Set stop loss to entry price
            "tp": position.tp,          # Preserve existing take profit (if any)
            # "type_time": mt5.ORDER_TIME_GTC, # Not needed for SLTP action
            # "type_filling": mt5.ORDER_FILLING_IOC # Not needed for SLTP action
           "comment": "PipSecure Entry"
        }

        # Add retry mechanism for order modification
        max_retries = 3
        for attempt in range(max_retries):
            try:
                # Ensure request dict is correctly formatted before sending
                # self.logger.debug(f"Sending order_send request: {request}")
                result = mt5.order_send(request)

                if result is None:
                    error_code = mt5.last_error()
                    error_desc = mt5.last_error()[1] if isinstance(mt5.last_error(), tuple) else str(mt5.last_error())
                    self.logger.error(f"Attempt {attempt + 1}/{max_retries}: order_send returned None for securing {position.ticket}")
                    self.logger.error(f"  - System error code: {error_code}")
                    self.logger.error(f"  - System error desc: {error_desc}")
                    self.summary_counters['errors'] += 1
                    if attempt < max_retries - 1:
                        time.sleep(1 + attempt) # Exponential backoff
                    continue

                # Check result code: https://www.mql5.com/en/docs/constants/tradingconstants/enum_trade_return_codes
                if result.retcode == mt5.TRADE_RETCODE_DONE:
                    self.logger.info(f"[SUCCESS] Successfully secured position {position.ticket} for {position.symbol}")
                    self.logger.info(f"  Stop loss moved to entry: {position.price_open}")
                    self.secured_positions.add(position.ticket)
                    self.summary_counters['positions_secured'] += 1
                    if log_as_tp1_hit:
                        self.summary_counters['tp1_secured_events'] += 1
                        # Log key event specifically for TP1 hit leading to secure
                        self.log_key_event("TP1_SECURED", f"Position {position.ticket} ({position.symbol}) secured at entry {position.price_open} after TP1 condition met.")
                    return True
                else:
                    # Log specific error message from result
                    self.logger.error(f"Attempt {attempt + 1}/{max_retries}: Failed to modify SL for {position.ticket}")
                    self.logger.error(f"  - Error code: {result.retcode}")
                    self.logger.error(f"  - Error message: {result.comment}")
                    self.summary_counters['errors'] += 1

                    # Specific handling for common errors
                    if result.retcode == mt5.TRADE_RETCODE_INVALID_STOPS:
                        self.logger.error("  - Reason: Invalid Stop Loss/Take Profit levels. SL might be too close to current market price.")
                        # Possibly add logic here to slightly adjust SL if allowed, or just fail.
                        break # Don't retry if stops are invalid
                    elif result.retcode == mt5.TRADE_RETCODE_REQUOTE:
                         self.logger.warning("  - Reason: Requote. Retrying...")
                         time.sleep(0.5) # Quick retry for requote
                         continue
                    elif result.retcode == mt5.TRADE_RETCODE_CONNECTION:
                         self.logger.error("  - Reason: Connection issue. Retrying...")
                         time.sleep(2)
                         continue


                    if attempt < max_retries - 1:
                        time.sleep(1 + attempt) # Exponential backoff
                    else:
                         # Log key event failure only after all retries
                        if log_as_tp1_hit:
                             self.log_key_event("TP1_SECURE_FAILED", f"Failed to secure position {position.ticket} ({position.symbol}) after TP1 condition met. Error: {result.retcode} - {result.comment}")


            except Exception as e:
                self.logger.error(f"Exception during order_send for securing {position.ticket}: {str(e)}", exc_info=True)
                self.summary_counters['errors'] += 1
                if attempt < max_retries - 1:
                    time.sleep(1 + attempt)

        return False # Failed after retries

    def identify_position_groups(self):
        """
        Identify groups of positions that belong to the same signal based on:
        1. Same symbol
        2. Same direction (buy/sell)
        3. Close entry times (using position.time - the open time)
        4. Similar entry prices (with more tolerance for certain instruments)
        """
        positions = mt5.positions_get()
        if positions is None:
            error_code, error_desc = mt5.last_error()
            # Throttle this specific error if it repeats
            self.log_throttled('error', f"Failed to get positions: {error_code} - {error_desc}", key="get_positions_fail")
            self.summary_counters['errors'] += 1
            return {}

        if not positions:
            self.logger.debug("No open positions found for grouping.")
            return {}

        # Sort positions primarily by time, then symbol, then type for consistent grouping
        try:
            sorted_positions = sorted(positions, key=lambda p: (p.time, p.symbol, p.type))
        except Exception as e:
            self.logger.error(f"Error sorting positions: {e}", exc_info=True)
            sorted_positions = list(positions) # Use unsorted if sort fails


        position_groups = {}
        group_counter = 0
        processed_tickets = set()

        for i, position in enumerate(sorted_positions):
            if position.ticket in processed_tickets:
                continue

            # Start a new potential group
            current_group = [position]
            processed_tickets.add(position.ticket)
            # Use position type directly in group ID (0 for Buy, 1 for Sell)
            group_id = f"{position.symbol}_{position.type}_{group_counter}" # More specific ID

            # Look at subsequent positions that are close in time
            for j in range(i + 1, len(sorted_positions)):
                other_position = sorted_positions[j]

                if other_position.ticket in processed_tickets:
                    continue

                # Check time difference first (most important)
                time_diff = abs(other_position.time - position.time)
                if time_diff > self.time_proximity_threshold:
                    # Since positions are sorted by time, we can break early
                    # if the symbol/type also matches, but check all for safety
                    continue # Too far apart in time

                # Check symbol and type
                if (other_position.symbol == position.symbol and
                    other_position.type == position.type):

                    # Set higher price tolerance for commodities and indices
               
                    price_proximity_override = None
                    if (position.symbol in ['OILCash', 'XAUUSDx', 'US30Cash', 'US100Cash', 'JP225Cash', 'GER40Cash'] or
                        'XAU' in position.symbol.upper() or 'GOLD' in position.symbol.upper()):
                        price_proximity_override = 100  # Increased from 20 to 100 pips for GOLD
                    
                        
                    
                    # Use the override if available, otherwise use default
                    price_threshold = price_proximity_override or self.price_proximity_threshold

                    # Optional: Check price proximity
                    pip_multiplier = self.get_pip_multiplier(position.symbol)
                    if pip_multiplier > 0: # Avoid division by zero
                        price_diff_in_pips = abs(other_position.price_open - position.price_open) / pip_multiplier
                        if price_diff_in_pips <= price_threshold:
                            # Add to the current group
                            current_group.append(other_position)
                            processed_tickets.add(other_position.ticket)
                            self.logger.debug(f"Added position {other_position.ticket} to group {group_id}: price diff {price_diff_in_pips:.1f} pips <= {price_threshold}")
                        else:
                            self.logger.debug(f"Skipping {other_position.ticket} from group {group_id}: price diff {price_diff_in_pips:.1f} pips > {price_threshold}")

                    else: # If pip_multiplier is 0 or invalid, rely only on time/symbol/type
                        current_group.append(other_position)
                        processed_tickets.add(other_position.ticket)


            # Only store groups with more than one position (representing multi-TP)
            if len(current_group) > 1:
                position_groups[group_id] = current_group
                group_counter += 1
                # Log the found group
                self.logger.debug(f"Identified position group: {group_id} with {len(current_group)} positions")
                for pos in current_group:
                    tp_val = getattr(pos, 'tp', 0) # Handle potential missing attribute in mocks/real data
                    self.logger.debug(f"  - Ticket: {pos.ticket}, Entry: {pos.price_open:.5f}, TP: {tp_val:.5f}, Time: {datetime.fromtimestamp(pos.time)}")

        return position_groups

    def get_position_index_in_group(self, position, group):
        """Determine the index (TP1, TP2, etc.) of a position within its group"""
        # Use the tracked TP level from comment instead of TP value comparison
        return self.get_position_tp_level(position)
    
    def get_position_tp_level(self, position):
        """Extract current TP level from position comment"""
        try:
            if hasattr(position, 'comment') and position.comment and "_TP" in position.comment:
                # Extract TP level from comment format: "G12345_TP2"
                tp_part = position.comment.split("_TP")[-1]
                return int(tp_part[0])  # Get first digit after _TP
            return 1  # Default to TP1
        except (ValueError, IndexError):
            return 1  # Default to TP1 on error

    def get_next_tp_price(self, position, signal_data, next_level):
        """Get the next TP price for progression"""
        try:
            # signal_data should contain original TP levels
            tp_levels = signal_data.get('tp_levels', [])
            if next_level <= len(tp_levels):
                return tp_levels[next_level - 1]  # TP levels are 0-indexed
            return None
        except (IndexError, KeyError):
            return None

    def secure_and_progress_tp(self, position, next_tp_price, next_tp_level, group_id):
        """Secure position AND progress to next TP in ONE atomic operation"""
        if next_tp_price is None:
            # No more TPs, close the position
            return self.close_position(position)
        
        # Update comment to reflect new TP level
        old_comment = getattr(position, 'comment', '')
        if "_TP" in old_comment:
            new_comment = old_comment.split("_TP")[0] + f"_TP{next_tp_level}"
        else:
            new_comment = f"G{group_id}_TP{next_tp_level}"
        
        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "position": position.ticket,
            "symbol": position.symbol,
            "sl": position.price_open,      # Secure at entry
            "tp": next_tp_price,            # Set next TP
            "comment": new_comment
        }
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                result = mt5.order_send(request)
                
                if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                    self.logger.info(f"✅ Secured position {position.ticket} and progressed to TP{next_tp_level} at {next_tp_price}")
                    self.secured_positions.add(position.ticket)
                    return True
                else:
                    self.logger.error(f"Attempt {attempt + 1}: Failed to secure and progress {position.ticket}")
                    if attempt < max_retries - 1:
                        time.sleep(1)
            except Exception as e:
                self.logger.error(f"Exception during secure_and_progress_tp: {e}")
                if attempt < max_retries - 1:
                    time.sleep(1)
        
        return False


    def diagnose_tp_values(self, group):
        """Diagnose TP values in a position group"""
        self.logger.info("🔍 DIAGNOSING TP VALUES:")
        
        for i, pos in enumerate(group):
            tp_val = getattr(pos, 'tp', 0)
            self.logger.info(f"  Position {i+1}: Ticket={pos.ticket}, Entry={pos.price_open:.2f}, TP={tp_val:.2f}, Current={pos.price_current:.2f}")
            
            # Calculate distance to TP
            if tp_val > 0:
                if pos.type == mt5.ORDER_TYPE_SELL:
                    distance_to_tp = pos.price_current - tp_val
                    self.logger.info(f"    Distance to TP: {distance_to_tp:.2f} points ({'HIT' if distance_to_tp <= 0 else 'NOT HIT'})")
                else:
                    distance_to_tp = tp_val - pos.price_current  
                    self.logger.info(f"    Distance to TP: {distance_to_tp:.2f} points ({'HIT' if distance_to_tp <= 0 else 'NOT HIT'})")
        
        # Check if all TPs are the same
        tp_values = [getattr(pos, 'tp', 0) for pos in group]
        unique_tps = set(tp_values)
        if len(unique_tps) == 1:
            self.logger.info(f"✅ All positions have same TP: {list(unique_tps)[0]}")
        else:
            self.logger.error(f"❌ DIFFERENT TP VALUES FOUND: {unique_tps}")

    def validate_signal_direction_logic(self, position, group):
            """Validate that BUY/SELL logic is applied correctly"""
            try:
                is_buy = position.type == mt5.ORDER_TYPE_BUY
                symbol = position.symbol
                
                # Log the position details for debugging
                self.logger.info(f"🔍 Direction Check - {symbol}:")
                self.logger.info(f"  Position Type: {'BUY' if is_buy else 'SELL'}")
                self.logger.info(f"  Entry: {position.price_open:.2f}")
                self.logger.info(f"  Current: {position.price_current:.2f}")
                self.logger.info(f"  TP: {getattr(position, 'tp', 0):.2f}")
                self.logger.info(f"  SL: {position.sl:.2f}")
                
                # Check if TP makes sense for the direction
                pos_tp = getattr(position, 'tp', 0)
                if pos_tp > 0:
                    if is_buy and pos_tp <= position.price_open:
                        self.logger.error(f"❌ BUY position TP ({pos_tp}) should be ABOVE entry ({position.price_open})")
                        return False
                    elif not is_buy and pos_tp >= position.price_open:
                        self.logger.error(f"❌ SELL position TP ({pos_tp}) should be BELOW entry ({position.price_open})")
                        return False
                
                # Check if SL makes sense for the direction  
                if is_buy and position.sl >= position.price_open:
                    self.logger.error(f"❌ BUY position SL ({position.sl}) should be BELOW entry ({position.price_open})")
                    return False
                elif not is_buy and position.sl <= position.price_open:
                    self.logger.error(f"❌ SELL position SL ({position.sl}) should be ABOVE entry ({position.price_open})")
                    return False
                    
                # Check price movement direction
                pip_multiplier = self.get_pip_multiplier(symbol)
                if is_buy:
                    pips_moved = (position.price_current - position.price_open) / pip_multiplier
                    self.logger.info(f"  BUY pips moved: {pips_moved:.1f} ({'profit' if pips_moved > 0 else 'loss'})")
                else:
                    pips_moved = (position.price_open - position.price_current) / pip_multiplier  
                    self.logger.info(f"  SELL pips moved: {pips_moved:.1f} ({'profit' if pips_moved > 0 else 'loss'})")
                
                return True
                
            except Exception as e:
                self.logger.error(f"Error in direction validation: {e}")
                return True  # Allow processing to continue

    def get_true_first_price_group(self, position_groups):
            """Get the group that represents the actual first price level based on signal logic"""
            
            if not position_groups:
                return None, None
                
            valid_groups = {gid: group for gid, group in position_groups.items() if len(group) > 1}
            
            if len(valid_groups) == 0:
                return None, None
                
            if len(valid_groups) == 1:
                # Only one group, it must be first price
                group_id = list(valid_groups.keys())[0]
                return valid_groups[group_id], group_id
            
            # Multiple groups - determine which is logically the first price
            # Get a sample position to determine direction
            sample_position = list(valid_groups.values())[0][0]
            is_sell = sample_position.type == mt5.ORDER_TYPE_SELL
            
            if is_sell:
                # For SELL: first price should be the LOWER entry (price falls to hit it first)
                lowest_group = min(valid_groups.items(), key=lambda x: sum(p.price_open for p in x[1])/len(x[1]))
                avg_entry = sum(p.price_open for p in lowest_group[1]) / len(lowest_group[1])
                self.logger.info(f"SELL: First price group identified (lowest entry): {lowest_group[0]}, avg: {avg_entry:.2f}")
                return lowest_group[1], lowest_group[0]
            else:
                # For BUY: first price should be the HIGHER entry (price rises to hit it first)  
                highest_group = max(valid_groups.items(), key=lambda x: sum(p.price_open for p in x[1])/len(x[1]))
                avg_entry = sum(p.price_open for p in highest_group[1]) / len(highest_group[1])
                self.logger.info(f"BUY: First price group identified (highest entry): {highest_group[0]}, avg: {avg_entry:.2f}")
                return highest_group[1], highest_group[0]



    def identify_pending_orders(self):
        """
        Identifies pending orders. Currently doesn't group them but returns all.
        Grouping logic might be added later if needed, similar to position grouping.
        """
        pending_orders = mt5.orders_get() # Gets both pending and active orders initially
        if pending_orders is None:
            error_code, error_desc = mt5.last_error()
            self.log_throttled('error', f"Failed to get orders: {error_code} - {error_desc}", key="get_orders_fail")
            self.summary_counters['errors'] += 1
            return [] # Return empty list on failure

        # Filter for actual pending orders
        # Order states: https://www.mql5.com/en/docs/constants/tradingconstants/orderproperties#enum_order_state
        # ORDER_STATE_PLACED -> Pending order
        # ORDER_STATE_STARTED -> Usually means it's being processed for execution? Let's include for safety.
        # We want orders that are *not* filled, canceled, rejected, expired etc.
        actual_pending = []
        for order in pending_orders:
             # Check necessary attributes exist before accessing
            if hasattr(order, 'state') and hasattr(order, 'type') and \
               order.state in [mt5.ORDER_STATE_PLACED, mt5.ORDER_STATE_STARTED] and \
               order.type in [
                    mt5.ORDER_TYPE_BUY_LIMIT, mt5.ORDER_TYPE_BUY_STOP,
                    mt5.ORDER_TYPE_SELL_LIMIT, mt5.ORDER_TYPE_SELL_STOP,
                    mt5.ORDER_TYPE_BUY_STOP_LIMIT, mt5.ORDER_TYPE_SELL_STOP_LIMIT
                ]:
                actual_pending.append(order)


        if not actual_pending:
            self.logger.debug("No pending orders found")
            return []

        self.logger.debug(f"Found {len(actual_pending)} pending orders.")
        # # Optional: Log details of pending orders if needed for debugging
        # for order in actual_pending:
        #      self.logger.debug(f"  - Pending Ticket: {order.ticket}, Symbol: {order.symbol}, Type: {order.type}, Price: {order.price_open}")

        # Currently not grouping, just returning the list
        return actual_pending

# Ensure Pending Orders are Found and Deleted
    def find_corresponding_pending_orders(self, position_group):
        """
        Finds pending orders that likely correspond to the 'next' price level
        for a given activated position group.
        """
        if not position_group:
            return None

        sample_position = position_group[0]
        symbol = sample_position.symbol
        position_type = sample_position.type

        # Get ALL orders for this symbol
        all_orders = mt5.orders_get(symbol=symbol)
        if not all_orders:
            self.logger.info(f"No orders found for {symbol}")
            return None

        # Filter for pending orders
        pending_orders = []
        for order in all_orders:
            # Check if it's a pending order (not filled or cancelled)
            if order.state == mt5.ORDER_STATE_PLACED:
                # Check if it matches the direction
                if position_type == mt5.ORDER_TYPE_BUY and order.type in [mt5.ORDER_TYPE_BUY_LIMIT, mt5.ORDER_TYPE_BUY_STOP]:
                    pending_orders.append(order)
                    self.logger.info(f"Found pending BUY order: {order.ticket} at {order.price_open}")
                elif position_type == mt5.ORDER_TYPE_SELL and order.type in [mt5.ORDER_TYPE_SELL_LIMIT, mt5.ORDER_TYPE_SELL_STOP]:
                    pending_orders.append(order)
                    self.logger.info(f"Found pending SELL order: {order.ticket} at {order.price_open}")

        return pending_orders if pending_orders else None


    def delete_pending_orders(self, orders_to_delete):
        """
        Deletes a list of pending orders.
        Returns the number of successfully deleted orders.
        """
        if not orders_to_delete:
            self.logger.info("No pending orders provided for deletion.")
            return 0

        deleted_count = 0
        self.logger.info(f"Attempting to delete {len(orders_to_delete)} pending orders...")

        for order in orders_to_delete:
            order_ticket = getattr(order, 'ticket', None)
            order_symbol = getattr(order, 'symbol', 'N/A')
            if order_ticket is None:
                self.logger.warning("Skipping order deletion: order object missing 'ticket' attribute.")
                continue

            self.logger.info(f"  Deleting pending order {order_ticket} for {order_symbol}...")
            request = {
                "action": mt5.TRADE_ACTION_REMOVE, # Action to remove pending order
                "order": order_ticket,            # Ticket of the pending order
                "comment": "PipSecure Delete"
            }

            # Send the request
            max_retries = 2
            for attempt in range(max_retries):
                try:
                    # self.logger.debug(f"Sending order_send request: {request}")
                    result = mt5.order_send(request)

                    if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                        self.logger.info(f"  [SUCCESS] Successfully deleted pending order {order_ticket}")
                        self.summary_counters['pending_orders_deleted'] += 1
                        self.summary_counters['pending_deleted_events'] += 1
                        # Log key event for deletion
                        self.log_key_event("PENDING_DELETED", f"Pending order {order_ticket} ({order_symbol}, Price: {getattr(order, 'price_open', 'N/A')}) deleted due to TP1 hit on related position.")
                        deleted_count += 1
                        break # Success, move to next order
                    elif result:
                        # Deletion failed
                        self.logger.error(f"  Attempt {attempt + 1}/{max_retries}: Failed to delete pending order {order_ticket}. Code: {result.retcode}, Msg: {result.comment}")
                        self.summary_counters['errors'] += 1
                        if attempt < max_retries - 1:
                            time.sleep(0.5 + attempt) # Short delay before retry
                        else:
                            # Log key event failure only after all retries
                            self.log_key_event("PENDING_DELETE_FAILED", f"Failed to delete pending order {order_ticket} ({order_symbol}). Error: {result.retcode} - {result.comment}")

                    else:
                        # order_send returned None
                        error_code, error_desc = mt5.last_error()
                        self.logger.error(f"  Attempt {attempt + 1}/{max_retries}: order_send returned None for deleting {order_ticket}. Error: {error_code} - {error_desc}")
                        self.summary_counters['errors'] += 1
                        if attempt < max_retries - 1:
                            time.sleep(1 + attempt)
                        else:
                            self.log_key_event("PENDING_DELETE_FAILED", f"Failed to delete pending order {order_ticket} ({order_symbol}). System Error: {error_code} - {error_desc}")
                except Exception as e:
                     self.logger.error(f"Exception during order_send for deleting {order_ticket}: {e}", exc_info=True)
                     self.summary_counters['errors'] += 1
                     if attempt == max_retries - 1:
                         self.log_key_event("PENDING_DELETE_FAILED", f"Failed to delete pending order {order_ticket} ({order_symbol}). Exception: {str(e)}")
                     if attempt < max_retries - 1: time.sleep(1+attempt)


        self.logger.info(f"Finished deletion attempt: {deleted_count} / {len(orders_to_delete)} orders successfully deleted.")
        return deleted_count

    def secure_second_price_positions(self, first_price_group, first_price_entry_value):
        """
        Secures positions that are likely from a 'second price level' by setting their
        stop loss to the entry price of the *first* price level.

        Args:
            first_price_group: List of positions from the first price level group.
            first_price_entry_value: The specific entry price value (e.g., average or TP1 entry)
                                    to use as the new Stop Loss.

        Returns:
            Number of second price positions successfully secured (request sent OK).
        """
        if not first_price_group or first_price_entry_value is None or first_price_entry_value == 0:
            self.logger.warning("Cannot secure second price positions: missing first price group or valid entry value.")
            return 0

        # Get details from the first group
        sample_position = first_price_group[0]
        symbol = sample_position.symbol
        position_type = sample_position.type
        first_price_tickets = {pos.ticket for pos in first_price_group} # Use a set for faster lookup

        self.logger.info(f"Searching for second price positions for {symbol} (Type: {'BUY' if position_type == mt5.ORDER_TYPE_BUY else 'SELL'}) to secure at SL={first_price_entry_value:.5f}")

        # Get all positions for this symbol and type
        all_symbol_positions = mt5.positions_get(symbol=symbol)
        if not all_symbol_positions:
            self.logger.info(f"No open positions found for {symbol} to check for second price.")
            return 0

        same_type_positions = [pos for pos in all_symbol_positions if pos.type == position_type]

        # Identify positions NOT in the first price group - these are candidates for the second price level
        second_price_candidates = [pos for pos in same_type_positions if pos.ticket not in first_price_tickets]

        if not second_price_candidates:
            self.logger.info(f"No other active positions found for {symbol} matching the type, presumed no second price level active.")
            return 0

        self.logger.info(f"Found {len(second_price_candidates)} candidate position(s) potentially from a second price level.")

        # Secure these candidate positions by moving SL to the first price entry
        secured_count = 0
        for position in second_price_candidates:
            # --- Refined Check: Skip if ALREADY secured by Rule 2 OR at its own entry ---
            if position.ticket in self.secured_positions:
                 symbol_info = mt5.symbol_info(position.symbol)
                 sl_threshold = 10**(-symbol_info.digits) if symbol_info else 0.00001

                 # Check if SL matches Rule 2 target
                 if abs(position.sl - first_price_entry_value) < sl_threshold:
                      self.log_throttled('info', f"Second price position {position.ticket} SL is already at first price entry {first_price_entry_value:.5f} (Rule 2 likely applied).", key=f"sec2_{position.ticket}")
                      continue # Already handled by Rule 2

                 # Check if SL matches its own entry (handled independently before?)
                 elif abs(position.sl - position.price_open) < sl_threshold:
                      self.logger.warning(f"Second price candidate position {position.ticket} was already secured at its *own* entry ({position.price_open:.5f}). Skipping Rule 2 modification.")
                      continue # Handled independently

                 # If in secured_positions but SL matches neither, log it but potentially proceed? Or assume it's handled? Let's skip.
                 else:
                      self.log_throttled('warning', f"Second price candidate {position.ticket} in secured_positions but SL ({position.sl}) matches neither own entry nor Rule 2 target. Skipping.", key=f"sec2_unk_{position.ticket}")
                      continue


            self.logger.info(f"[TARGET RULE 2] Securing second price position {position.ticket} ({position.symbol})")
            self.logger.info(f"  Setting SL to FIRST price entry: {first_price_entry_value:.5f} (Original Entry: {position.price_open:.5f}, Current SL: {position.sl:.5f})")

            request = {
                "action": mt5.TRADE_ACTION_SLTP,
                "position": position.ticket,
                "symbol": position.symbol,
                "sl": first_price_entry_value, # <<< Key part of RULE 2
                "tp": position.tp,             # Keep original TP
                "comment": "PipSecure 1st"
            }

            # Send the request (with retries)
            max_retries = 3
            success_sent = False # Flag to track if sending request succeeded
            for attempt in range(max_retries):
                try:
                    # self.logger.debug(f"Sending order_send request: {request}")
                    result = mt5.order_send(request)

                    if result is None:
                        error_code, error_desc = mt5.last_error()
                        self.logger.error(f"Attempt {attempt + 1}/{max_retries}: order_send returned None for securing 2nd price {position.ticket}")
                        self.logger.error(f"  - System error: {error_code} - {error_desc}")
                        self.summary_counters['errors'] += 1
                        if attempt < max_retries - 1: time.sleep(1 + attempt)
                        continue

                    if result.retcode == mt5.TRADE_RETCODE_DONE:
                        self.logger.info(f"[SUCCESS RULE 2] Successfully sent request to secure second price position {position.ticket}")
                        self.logger.info(f"  Stop loss intended for first price entry: {first_price_entry_value:.5f}")
                        # Log Key Event for Rule 2
                        self.log_key_event("SECOND_PRICE_SECURED", f"Position {position.ticket} ({position.symbol}, Entry: {position.price_open:.5f}) secured with SL at FIRST price entry {first_price_entry_value:.5f} (Rule 2).")

                        # --- !!! IMPORTANT: Update internal state immediately !!! ---
                        # Mark this position as handled by Rule 2 so the main loop skips it.
                        self.secured_positions.add(position.ticket)
                        # --- End Important Update ---

                        self.summary_counters['positions_secured'] += 1 # Count towards total secured
                        self.summary_counters['second_price_secured_events'] += 1
                        secured_count += 1
                        success_sent = True # Mark success
                        break # Success for this position
                    else:
                        self.logger.error(f"Attempt {attempt + 1}/{max_retries}: Failed to modify SL for 2nd price {position.ticket} (Rule 2)")
                        self.logger.error(f"  - Error code: {result.retcode}")
                        self.logger.error(f"  - Error message: {result.comment}")
                        self.summary_counters['errors'] += 1
                        # Check for specific non-retryable errors like invalid stops
                        if result.retcode == mt5.TRADE_RETCODE_INVALID_STOPS:
                             self.logger.error(f"  - Reason: Invalid Stop Loss level {first_price_entry_value:.5f}. Might be too close to market.")
                             # Log Key Event for Rule 2 Failure
                             self.log_key_event("SECOND_PRICE_SECURE_FAILED", f"Failed to secure position {position.ticket} ({position.symbol}) with SL at first price entry {first_price_entry_value:.5f}. Invalid SL.")
                             break # Don't retry invalid stops
                        elif attempt < max_retries - 1:
                             time.sleep(1 + attempt)
                        else:
                            # Log key event failure after all retries
                             self.log_key_event("SECOND_PRICE_SECURE_FAILED", f"Failed to secure position {position.ticket} ({position.symbol}) with SL at first price entry {first_price_entry_value:.5f}. Error: {result.retcode} - {result.comment}")


                except Exception as e:
                    self.logger.error(f"Exception during order_send for securing 2nd price {position.ticket}: {str(e)}", exc_info=True)
                    self.summary_counters['errors'] += 1
                    if attempt == max_retries - 1:
                        # Log key event failure after exception
                        self.log_key_event("SECOND_PRICE_SECURE_FAILED", f"Failed to secure position {position.ticket} ({position.symbol}) with SL at first price entry {first_price_entry_value:.5f}. Exception: {str(e)}")
                    if attempt < max_retries - 1:
                        time.sleep(1+attempt)


        self.logger.info(f"Finished securing second price positions: {secured_count} / {len(second_price_candidates)} successfully had secure request sent (Rule 2).")
        return secured_count


    def check_positions(self):
        """
        Main logic loop: Checks all positions, identifies groups, applies securing rules,
        and handles multi-price level logic (Rules 1 & 2).
        """
        try:
            start_time = time.time()
            
            # Add position age and profit requirements
            MIN_POSITION_AGE_SECONDS = 300  # 5 minutes minimum
            MIN_PIPS_FOR_SECURE = 5  # Minimum 5 pips profit
            
            # Track TP1 hits - IMPORTANT: This should persist between cycles
            if not hasattr(self, 'tp1_hit_groups'):
                self.tp1_hit_groups = set()  # Track groups where TP1 was actually hit
            # Set to track which TP1 groups have triggered an action in this cycle
            tp1_action_triggered_groups = set()
            # Verify MT5 connection is still active
            terminal_info = mt5.terminal_info()
            if not terminal_info or terminal_info.connected is False:
                self.logger.error("MT5 connection lost - attempting to reconnect...")
                self.summary_counters['errors'] += 1
                if not self.connect():
                    self.logger.error("Failed to reconnect to MT5. Will retry next cycle.")
                    time.sleep(30)
                    return
                else:
                    self.logger.info("Successfully reconnected to MT5.")

            # Get positions
            positions = mt5.positions_get()
            if positions is None:
                error_code, error_desc = mt5.last_error()
                self.log_throttled('error', f"Failed to get positions: {error_code} - {error_desc}", key="check_get_pos_fail")
                self.summary_counters['errors'] += 1
                return
            # In check_positions method, add after getting positions:
            for position in positions:
                if 'XAU' in position.symbol.upper() or 'GOLD' in position.symbol.upper():
                     pass  # Do nothing for GOLD
                    

            # Update active symbols
            current_active_symbols = {pos.symbol for pos in positions}
            self.active_symbols.update(current_active_symbols)
            self.summary_counters['positions_checked'] += len(positions)

            if not positions:
                self.logger.debug("No open positions found to check.")
                if self.secured_positions:
                    self.logger.info("Clearing secured positions tracker as no positions are open.")
                    self.secured_positions.clear()
                # Also clear TP1 hit tracker when no positions
                if hasattr(self, 'tp1_hit_groups'):
                    self.tp1_hit_groups.clear()
                return

            # Identify position groups
            position_groups = self.identify_position_groups()
            
            # Clean up tp1_hit_groups - remove groups that no longer exist
            existing_group_ids = set(position_groups.keys())
            self.tp1_hit_groups = self.tp1_hit_groups.intersection(existing_group_ids)

            # Process each position
            for position in list(positions):
                try:
                    symbol = position.symbol

                    # Skip if already secured
                    if position.ticket in self.secured_positions:
                        self.log_throttled('debug', f"Position {position.ticket} is in secured set. Skipping.", key=f"secured_skip_{position.ticket}")
                        continue

                    # Check position age
                    position_age = time.time() - position.time
                    if position_age < MIN_POSITION_AGE_SECONDS:
                        self.logger.debug(f"Position {position.ticket} too young ({position_age:.0f}s), skipping secure check")
                        continue
                    # Initialize variables for each position
                    position_index = None
                    group_id = None
                    group = None
                    # Check profit
                    pip_multiplier = self.get_pip_multiplier(symbol)
                    if pip_multiplier == 0:
                        self.logger.warning(f"Invalid pip multiplier 0 for {symbol}")
                        continue
                        
                    pips_gained = 0
                    is_buy = position.type == mt5.ORDER_TYPE_BUY
                    
                    if is_buy:
                        pips_gained = (position.price_current - position.price_open) / pip_multiplier
                    else:
                        pips_gained = (position.price_open - position.price_current) / pip_multiplier

                    # Find group
                    group = None
                    group_id = None
                    for gid, group_positions in position_groups.items():
                        if any(p.ticket == position.ticket for p in group_positions):
                            group = group_positions
                            group_id = gid
                            break

                    # Process grouped positions
                        if group:
                            self.diagnose_tp_values(group)
                            # Add validation for BUY/SELL logic
                            if not self.validate_signal_direction_logic(position, group):
                                self.logger.error(f"❌ Direction logic validation failed for {position.ticket}")
                                continue
                            # Find the true first price group
                            true_first_price_group, true_first_price_group_id = self.get_true_first_price_group(position_groups)
                            position_index = self.get_position_index_in_group(position, group)
                            if position_index is None:
                                self.logger.debug(f"Could not determine TP index for position {position.ticket} in group {group_id}. Skipping TP logic.")
                                continue                       
                    self.logger.debug(
                        f"Processing grouped position {position.ticket} (TP{position_index}) "
                        f"in group {group_id} - {symbol}. "
                        f"Entry: {position.price_open:.5f}, SL: {position.sl:.5f}, TP: {getattr(position, 'tp', 0):.5f}, Current: {position.price_current:.5f}"
                    )

                    # --- Rule Trigger: Check TP1 for Securing Conditions (ONLY for true first price group) ---
                    if position_index == 1 and group_id == true_first_price_group_id and group_id not in tp1_action_triggered_groups:
                        # ... rest of your existing TP1 logic stays the same ...                       
                        if position_index is None:
                            self.logger.debug(f"Could not determine TP index for position {position.ticket}")
                            continue

                        self.logger.debug(
                            f"Processing position {position.ticket} (TP{position_index}) "
                            f"Entry: {position.price_open:.5f}, Current: {position.price_current:.5f}, "
                            f"TP: {getattr(position, 'tp', 0):.5f}"
                        )

                        # Check TP1 position
                        

                        # Check TP1 position - but only if this group was actually entered by market
                        if position_index == 1 and group_id not in tp1_action_triggered_groups:
                            # NEW: Check if this group should be evaluated based on market entry
                            if not self.should_evaluate_tp_conditions(group, position.price_current):
                                self.logger.debug(f"Skipping TP evaluation for group {group_id} - entry level not hit yet")
                                continue
                                
                            # Original TP1 checking logic continues here...



                        # Calculate metrics
                        pips_gained = 0
                        is_buy = position.type == mt5.ORDER_TYPE_BUY
                        
                        if is_buy:
                            pips_gained = (position.price_current - position.price_open) / pip_multiplier
                        else:
                            pips_gained = (position.price_open - position.price_current) / pip_multiplier

                        # Calculate distance to TP
                        pos_tp = getattr(position, 'tp', 0)
                        if pos_tp == 0:
                            continue
                            
                        pips_to_tp = float('inf')
                        total_tp_pips = 0
                        tp_progress_percent = 0
                        
                        if is_buy:
                            pips_to_tp = (pos_tp - position.price_current) / pip_multiplier
                            total_tp_pips = (pos_tp - position.price_open) / pip_multiplier
                        else:
                            pips_to_tp = (position.price_current - pos_tp) / pip_multiplier
                            total_tp_pips = (position.price_open - pos_tp) / pip_multiplier

                        if abs(total_tp_pips) > 0.1:
                            tp_progress_percent = (pips_gained / total_tp_pips) * 100

                        # Check if we should take action
                        should_act = False
                        action_reason = ""

                        # 🧪 TEST MODE CONDITIONS (much easier to trigger)
                        if self.TEST_MODE:
                            if pips_to_tp <= 10:
                                should_act = True
                                action_reason = f"TEST MODE: within 10 pips of TP1 ({pips_to_tp:.1f} pips away)"
                            elif tp_progress_percent >= 25:
                                should_act = True
                                action_reason = f"TEST MODE: reached {tp_progress_percent:.1f}% of distance to TP1"
                            elif pips_gained >= 1:
                                should_act = True
                                action_reason = f"TEST MODE: gained {pips_gained:.1f} pips"
                            else:
                                # NEW FAIR APPROACH FOR MULTI-GROUP SCENARIOS
                                if len(position_groups) > 1:
                                    # Multi-group: Use distance-only (fair for all groups)
                                    if pips_to_tp <= 3:
                                        should_act = True
                                        action_reason = f"within 3 pips of TP1 ({pips_to_tp:.1f} pips away) - multi-group mode"
                                else:
                                    # Single-group: Use original system (distance + percentage)
                                    if pips_to_tp <= 3:
                                        should_act = True
                                        action_reason = f"within 3 pips of TP1 ({pips_to_tp:.1f} pips away)"
                                    elif tp_progress_percent >= 80:
                                        should_act = True
                                        action_reason = f"reached {tp_progress_percent:.1f}% of distance to TP1"

                        # Adjust minimum profit for test mode
                        min_pips_required = 1 if self.TEST_MODE else 5

                        if should_act and pips_gained >= min_pips_required:
                            self.logger.info(f"TP1 trigger condition met for {position.ticket} ({symbol}): {action_reason}")
                            tp1_action_triggered_groups.add(group_id)
                            self._save_tp1_hit_group(group_id)
                            # Action 1: Close TP1 position
                            self.logger.info(f"Action 1: Closing TP1 position {position.ticket}")
                        if should_act and pips_gained >= min_pips_required:
                            self.logger.info(f"TP1 trigger condition met for {position.ticket} ({symbol}): {action_reason}")
                            tp1_action_triggered_groups.add(group_id)
                            self._save_tp1_hit_group(group_id)
                            
                            # Check if this uses progressive TP system
                            if self.progressive_tp_manager.should_handle_tp_progression(position, group, group_id):
                                # Progressive TP handling
                                self.logger.info(f"Progressive TP: Handling TP hit for {position.ticket}")
                                self.progressive_tp_manager.handle_tp_hit(position, group, group_id)
                                
                                # Still secure other positions in group
                                self.logger.info(f"Action 2: Securing other positions in group {group_id}")
                                for other_pos in group:
                                    if other_pos.ticket != position.ticket and other_pos.ticket not in self.secured_positions:
                                        self.logger.info(f"Securing related position {other_pos.ticket}")
                                        self.secure_position(other_pos, log_as_tp1_hit=False)
                            else:
                                # Original logic for non-progressive positions
                                self.logger.info(f"Action 1: Closing TP1 position {position.ticket}")
                                if self.close_position(position):
                                    self.logger.info(f"TP1 position {position.ticket} closed successfully")
                                    
                                    # Action 2: Secure other positions in the group
                                    self.logger.info(f"Action 2: Securing other positions in group {group_id}")
                                    for other_pos in group:
                                        if other_pos.ticket != position.ticket and other_pos.ticket not in self.secured_positions:
                                            self.logger.info(f"Securing related position {other_pos.ticket} (TP{self.get_position_index_in_group(other_pos, group)})")
                                            self.secure_position(other_pos, log_as_tp1_hit=False)
                            
                            # Action 3: Delete pending orders (keep this unchanged)
                            self.logger.info(f"Action 3: Deleting pending orders for {symbol}")
                            corresponding_pending = self.find_corresponding_pending_orders(group)
                            if corresponding_pending:
                                self.logger.info(f"Found {len(corresponding_pending)} pending orders. Deleting...")
                                deleted_count = self.delete_pending_orders(corresponding_pending)
                                self.logger.info(f"Deleted {deleted_count} pending orders")
                            else:
                                self.logger.info(f"No pending orders found, checking for second price positions")
                                first_price_entry = position.price_open
                                self.secure_second_price_positions(group, first_price_entry)
                        
                        # Check other positions if TP1 in group was hit (either in this cycle or previously)
                        elif position_index > 1 and (group_id in self.tp1_hit_groups or group_id in tp1_action_triggered_groups):
                            if position.ticket not in self.secured_positions:
                                self.logger.info(f"Securing position {position.ticket} (TP{position_index}) because TP1 was hit")
                                self.secure_position(position, log_as_tp1_hit=False)   

                    else:
                        # Standalone positions
                        self.log_throttled('debug', f"Skipping standalone position {position.ticket}", key=f"skip_standalone_{symbol}")
                    continue  # Skip standalone positions
                except Exception as e:
                    self.logger.error(f"Error processing position {position.ticket}: {str(e)}", exc_info=True)
                    self.summary_counters['errors'] += 1

            # Log summary
            self.log_summary()
            
            execution_time = time.time() - start_time
            self.logger.debug(f"Position check completed in {execution_time:.3f} seconds")

        except Exception as e:
            self.logger.critical(f"Critical error in check_positions: {str(e)}", exc_info=True)
            self.summary_counters['errors'] += 1
            
      #tp1 close when 5 pips reach      
    def close_position(self, position):
        """Close a specific position with simple filling mode approach"""
        try:
            # Get current price
            tick = mt5.symbol_info_tick(position.symbol)
            if tick is None:
                self.logger.error(f"Failed to get tick data for {position.symbol}")
                return False
                
            # Determine closing price and type
            if position.type == mt5.ORDER_TYPE_BUY:
                close_type = mt5.ORDER_TYPE_SELL
                close_price = tick.bid
            else:
                close_type = mt5.ORDER_TYPE_BUY
                close_price = tick.ask
            
            # Build the basic request without filling mode
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "position": position.ticket,
                "symbol": position.symbol,
                "volume": position.volume,
                "type": close_type,
                "price": close_price,
                "deviation": 20,
                "comment": "PipSecureEA: TP1 Close",
            }
            
            # Try different filling modes in order of likelihood
            filling_modes = [
                mt5.ORDER_FILLING_IOC,
                mt5.ORDER_FILLING_FOK,
                mt5.ORDER_FILLING_RETURN,
                None  # Try without filling mode as last resort
            ]
            
            for filling_mode in filling_modes:
                try:
                    if filling_mode is not None:
                        request["type_filling"] = filling_mode
                    else:
                        request.pop("type_filling", None)
                    
                    self.logger.debug(f"Trying to close position {position.ticket} with filling mode: {filling_mode}")
                    
                    result = mt5.order_send(request)
                    
                    if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                        self.logger.info(f"[SUCCESS] Closed position {position.ticket} at {close_price}")
                        return True
                    elif result:
                        self.logger.debug(f"Failed with filling mode {filling_mode}: {result.comment}")
                        # If it's not a filling mode error, don't try other modes
                        if "filling" not in result.comment.lower():
                            self.logger.error(f"Failed to close position {position.ticket}: {result.comment}")
                            return False
                            
                except AttributeError:
                    # This filling mode constant doesn't exist, try next one
                    continue
                except Exception as e:
                    self.logger.debug(f"Error with filling mode {filling_mode}: {str(e)}")
                    continue
            
            self.logger.error(f"Failed to close position {position.ticket} after trying all filling modes")
            return False
                
        except Exception as e:
            self.logger.error(f"Error closing position {position.ticket}: {str(e)}")
            return False
    
    def run(self):
        """
        The main execution loop for a single PipSecureEA instance.
        Connects, checks positions periodically, and disconnects on exit.
        """
        self.logger.info(f"Starting PipSecureEA monitoring for account {self.account_name}")
        
        # 🧪 TEST MODE INDICATOR
        if self.TEST_MODE:
            self.logger.info("🧪 RUNNING IN TEST MODE")
        
        if self.connect():
            try:
                # 🧪 CREATE TEST POSITIONS IF IN TEST MODE
                if self.TEST_MODE:
                    self.logger.info("⏳ Creating test positions...")
                    time.sleep(3)  # Wait for connection stability
                    if self.create_test_positions():
                        self.logger.info("✅ Test positions created successfully")
                    else:
                        self.logger.error("❌ Failed to create test positions")
                        return
                
                # Main execution loop
                while True:
                    # --- Main Loop Actions ---
                    self.check_positions()
                    self.heartbeat.update_heartbeat() # Update heartbeat regularly

                    # --- Sleep Interval ---
                    time.sleep(1) # Check every second

            except KeyboardInterrupt:
                self.logger.info(f"KeyboardInterrupt received for account {self.account_name}. Shutting down.")
            except Exception as e:
                self.logger.critical(f"Unhandled exception in main run loop for {self.account_name}: {e}", exc_info=True)
            finally:
                self.logger.info(f"Disconnecting EA for account {self.account_name}.")
                self.disconnect()
                self.log_summary(force=True) # Log final summary
        else:
            self.logger.error(f"Could not connect account {self.account_name}. EA will not run.")
class ProgressiveTPManager:
    """Manages progressive TP placement and tracking"""
    
    def __init__(self, pip_secure_ea):
        self.ea = pip_secure_ea
        self.logger = pip_secure_ea.logger
        # Store original signal data for TP progression
        self.signal_data_cache = {}  # group_id -> signal_data
    
    def cache_signal_data(self, group_id, tp_levels):
        """Cache original TP levels for later progression"""
        self.signal_data_cache[group_id] = {
            'tp_levels': tp_levels,
            'created_at': time.time()
        }
        # Clean old cache entries (older than 24 hours)
        current_time = time.time()
        self.signal_data_cache = {
            gid: data for gid, data in self.signal_data_cache.items()
            if current_time - data['created_at'] < 86400
        }
    
    def handle_tp_hit(self, position, group, group_id):
        """Handle TP hit with progressive advancement"""
        current_level = self.ea.get_position_tp_level(position)
        self.logger.info(f"🎯 TP{current_level} hit for position {position.ticket}")
        
        # Get cached signal data
        signal_data = self.signal_data_cache.get(group_id, {})
        
        if current_level < 4:  # Can progress to next TP
            next_level = current_level + 1
            next_tp_price = self.ea.get_next_tp_price(position, signal_data, next_level)
            
            if next_tp_price:
                # Secure and progress atomically
                success = self.ea.secure_and_progress_tp(position, next_tp_price, next_level, group_id)
                if success:
                    self.logger.info(f"✅ Position {position.ticket} progressed from TP{current_level} to TP{next_level}")
                else:
                    self.logger.error(f"❌ Failed to progress position {position.ticket}")
            else:
                # No more TPs, close position
                self.logger.info(f"🔚 No more TPs for {position.ticket}, closing position")
                self.ea.close_position(position)
        else:
            # TP4 hit, close position
            self.logger.info(f"🏁 TP4 hit for {position.ticket}, closing position")
            self.ea.close_position(position)
    
    def should_handle_tp_progression(self, position, group, group_id):
        """Check if this position should use progressive TP handling"""
        # Only handle progression for positions with our comment format
        comment = getattr(position, 'comment', '')
        return "_TP" in comment and group_id in self.signal_data_cache                
# ------------------------------------------------------------------------
# SOLUTION 1: MULTI-ACCOUNT MONITOR CLASS (Manages multiple EA instances)
# ------------------------------------------------------------------------

class MultiAccountMonitor:
    def __init__(self, config_file='accounts_config.json'):
        self.config_file = config_file
        self.accounts = []
        self.processes = {} # Dictionary to store name -> process object
        self.monitored_accounts = set() # Track names of accounts being monitored

        # --- MOVED LOGGER INITIALIZATION HERE ---
        # Basic logger for the monitor itself (must be initialized before use)
        self.monitor_logger = logging.getLogger("MultiAccountMonitor")
        if not self.monitor_logger.handlers: # Avoid adding handlers multiple times
             handler = logging.StreamHandler(sys.stdout)
             formatter = logging.Formatter('%(asctime)s - [Monitor] - %(levelname)s - %(message)s')
             handler.setFormatter(formatter)
             self.monitor_logger.addHandler(handler)
             self.monitor_logger.setLevel(logging.INFO)
             self.monitor_logger.propagate = False
        # --- LOGGER INITIALIZED ---

        # --- NOW CALL _load_config ---
        self._load_config() # Now self.monitor_logger exists


    def _load_config(self):
        try:
            # Make sure monitor_logger exists before trying to use it
            if not hasattr(self, 'monitor_logger'):
                 print("Error: Monitor logger not initialized before loading config.")
                 sys.exit(1) # Cannot proceed without logger

            with open(self.config_file, 'r') as f:
                self.accounts = json.load(f)
            self.monitor_logger.info(f"Loaded configuration for {len(self.accounts)} accounts from {self.config_file}")

        except FileNotFoundError:
            # Log error now that logger exists
            self.monitor_logger.error(f"Configuration file {self.config_file} not found.")
            create_sample_config() # Create a sample if not found
            sys.exit(1) # Exit after creating sample
        except json.JSONDecodeError:
            self.monitor_logger.error(f"Invalid JSON format in {self.config_file}.")
            sys.exit(1)
        except Exception as e:
             self.monitor_logger.error(f"Error loading configuration: {e}", exc_info=True) # Add exc_info
             sys.exit(1)


    @staticmethod
    def _run_ea_process(account_config):
        """Static method to be run in a separate process for one account."""
        try:
            # Create and run the EA instance for this specific account
            ea = PipSecureEA(account_config)
            ea.run() # This method now contains the connect/loop/disconnect logic
        except Exception as e:
            # Log critical errors within the process if possible
            # Using print as logger setup might fail or be specific to the instance
            account_name_err = account_config.get('name', 'Unknown')
            print(f"CRITICAL ERROR in process for account {account_name_err}: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc() # Print full traceback from the process


    def run(self):
        # Ensure logger exists before starting
        if not hasattr(self, 'monitor_logger'):
             print("CRITICAL: Monitor logger failed to initialize. Exiting.")
             sys.exit(1)

        self.monitor_logger.info("Starting Multi-Account Monitor")

        # Start a process for each account
        for account_config in self.accounts:
            account_name = account_config.get('name', f"Login_{account_config.get('login', 'Unknown')}")
            if not account_config.get('login'): # Check for essential login info
                 self.monitor_logger.warning(f"Skipping account entry with missing login in config: {account_config}")
                 continue
            # Ensure name is derived if missing
            if not account_config.get('name'):
                 account_name = f"Login_{account_config['login']}" # Ensure defined name
                 self.monitor_logger.warning(f"Account config missing 'name', using default: {account_name}")


            try:
                 p = Process(target=self._run_ea_process, args=(account_config,), name=f"EA_{account_name}")
                 self.processes[account_name] = p
                 p.start()
                 self.monitor_logger.info(f"Started process PID {p.pid} for account '{account_name}'")
                 self.monitored_accounts.add(account_name)
                 time.sleep(1) # Slightly shorter stagger
            except Exception as e:
                 self.monitor_logger.error(f"Failed to start process for account '{account_name}': {e}", exc_info=True) # Add exc_info


        # Monitor the processes
        try:
            while True:
                time.sleep(30) # Check process status every 30 seconds
                processes_to_remove = [] # Collect names to remove after iteration

                for name, process in self.processes.items(): # Iterate over items
                    if not process.is_alive():
                        exitcode = process.exitcode
                        self.monitor_logger.error(f"Process for account '{name}' (PID {process.pid}) terminated unexpectedly with exit code {exitcode}.")
                        processes_to_remove.append(name)
                        if name in self.monitored_accounts:
                             self.monitored_accounts.remove(name) # Keep monitored_accounts sync

                        # Optional: Implement restart logic here if desired

                # Remove dead processes from the dictionary
                for name in processes_to_remove:
                    if name in self.processes: # Check if not already removed
                         del self.processes[name]

                if not self.processes and processes_to_remove: # Only exit if processes *were* running and *all* were removed now
                     self.monitor_logger.warning("All monitored processes have terminated.")
                     break # Exit monitor if no processes left

                if not self.processes and not processes_to_remove and self.monitored_accounts:
                     # Handles case where processes failed to start initially
                     self.monitor_logger.warning("No active processes running, but monitor was started. Exiting.")
                     break


        except KeyboardInterrupt:
            self.monitor_logger.info("KeyboardInterrupt received. Terminating all account processes...")
            for name, process in list(self.processes.items()): # Use list copy for safe iteration
                try:
                    if process.is_alive():
                        self.monitor_logger.info(f"Terminating process for account '{name}' (PID {process.pid})...")
                        process.terminate()
                        process.join(timeout=5)
                        if process.is_alive():
                             self.monitor_logger.warning(f"Process {process.pid} did not terminate gracefully, killing.")
                             process.kill()
                             process.join(timeout=2)
                    # Clean up dictionary even if termination fails/process already dead
                    if name in self.processes: del self.processes[name]

                except Exception as e:
                     self.monitor_logger.error(f"Error terminating process for {name}: {e}")

            self.monitor_logger.info("All processes terminated.")
        except Exception as e:
             self.monitor_logger.critical(f"Unhandled exception in MultiAccountMonitor run loop: {e}", exc_info=True)
             # Attempt graceful termination on unexpected error
             self.monitor_logger.info("Attempting emergency termination of account processes...")
             for name, process in list(self.processes.items()):
                 # (Similar termination logic as KeyboardInterrupt)
                 try:
                      if process.is_alive(): process.terminate(); process.join(1)
                      if process.is_alive(): process.kill(); process.join(1)
                 except: pass # Ignore errors during emergency shutdown
             self.monitor_logger.info("Emergency termination attempt complete.")


# ------------------------------------------------------------------------
# SOLUTION 2: SINGLE-ACCOUNT SCRIPT RUNNER FUNCTION
# ------------------------------------------------------------------------

    def run_single_account(account_name):
        """Loads config and runs the EA for a single specified account."""
        config_file = 'accounts_config.json'
        account_config = None
        print(f"Attempting to run in single-account mode for: {account_name}")

        # Load the master config file to find the specific account
        try:
            with open(config_file, 'r') as f:
                accounts = json.load(f)

            # Find the specified account config
            for acc in accounts:
                # Match by name, case-insensitive comparison might be safer
                if acc.get('name', '').lower() == account_name.lower():
                    account_config = acc
                    break

            if not account_config:
                print(f"ERROR: Account '{account_name}' not found in configuration file '{config_file}'")
                sys.exit(1)

            print(f"Found configuration for account '{account_name}'. Starting EA...")
            # Create and run the EA instance for this account
            ea = PipSecureEA(account_config)
            ea.run() # This handles connect, loop, disconnect

        except FileNotFoundError:
            print(f"ERROR: Configuration file '{config_file}' not found.")
            create_sample_config()
            sys.exit(1)
        except json.JSONDecodeError:
            print(f"ERROR: Invalid JSON format in configuration file '{config_file}'.")
            sys.exit(1)
        except KeyboardInterrupt:
            # The EA's run method should handle this, but we add a message here too.
            print(f"\nMonitoring stopped by user for account '{account_name}'.")
        except Exception as e:
            print(f"ERROR during single account execution for '{account_name}': {e}")
            import traceback
            traceback.print_exc() # Print detailed traceback for debugging
            sys.exit(1)


# ------------------------------------------------------------------------
# UTILITY FUNCTION TO CREATE SAMPLE CONFIG
# ------------------------------------------------------------------------

    def create_sample_config():
        sample_config = [
            {
                "name": "XM_Demo", # Use descriptive names
                "login": 98509933,
                "password": "@Xmm232425",
                "server": "XMGlobal-MT5 5",
                "terminal_path": "C:/Program Files/XM Global MT5/terminal64.exe"
            },
            {
                "name": "TNFX_Demo",
                "login": 549357,
                "password": "@Tnf232425",
                "server": "TNFX-Demo",
                "terminal_path": "C:/Program Files/TNFX Ltd MetaTrader 5 Terminal/terminal64.exe"
            },
            # Add more accounts here
            # {
            #     "name": "AnotherBroker_Live",
            #     "login": 12345678,
            #     "password": "YourSecurePassword",
            #     "server": "BrokerServer-Live",
            #     "terminal_path": "C:/Path/To/Another/MT5/terminal64.exe" # Optional if in default location or PATH
            # }
        ]
        config_file = 'accounts_config.json'
        try:
            with open(config_file, 'w') as f:
                json.dump(sample_config, f, indent=4)
            print(f"\nCreated sample configuration file: {config_file}")
            print("IMPORTANT: Please EDIT this file with your correct account details and terminal paths.")
        except Exception as e:
            print(f"\nERROR: Could not create sample config file {config_file}: {e}")


# ------------------------------------------------------------------------
# UTILITY FUNCTION TO CHECK EA STATUS VIA HEARTBEATS
# ------------------------------------------------------------------------

    def check_ea_status(max_age_minutes=5):
        """
        Checks EA status based on heartbeat files found in the 'heartbeats' directory.
        """
        import glob

        heartbeat_dir = 'heartbeats'
        print(f"\n--- EA Heartbeat Status Check (Stale if > {max_age_minutes} minutes old) ---")
        if not os.path.exists(heartbeat_dir) or not os.path.isdir(heartbeat_dir):
            print(f"Heartbeat directory '{heartbeat_dir}' not found.")
            print("-" * 50)
            return

        heartbeat_files = glob.glob(os.path.join(heartbeat_dir, '*_heartbeat.txt'))
        if not heartbeat_files:
            print("No heartbeat files found.")
            print("-" * 50)
            return

        current_time = datetime.now()
        print(f"Current time: {current_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print("-" * 50)

        stale_count = 0
        active_count = 0

        for hb_file in sorted(heartbeat_files):
            try:
                account_name = os.path.basename(hb_file).replace('_heartbeat.txt', '')
                monitor = HeartbeatMonitor(account_name, heartbeat_dir=heartbeat_dir) # Pass dir just in case

                last_heartbeat = monitor.get_last_heartbeat()
                if last_heartbeat is None:
                    print(f"Account: {account_name:<20} | Status: UNKNOWN (No valid heartbeat data)")
                    continue

                age = current_time - last_heartbeat
                age_minutes = age.total_seconds() / 60

                if monitor.is_stale(max_age_minutes):
                    status = "STALE"
                    stale_count += 1
                else:
                    status = "ACTIVE"
                    active_count += 1

                print(f"Account: {account_name:<20} | Status: {status:<7} | Last Beat: {last_heartbeat.strftime('%Y-%m-%d %H:%M:%S')} ({age_minutes:.1f} min ago)")

            except Exception as e:
                print(f"Error processing heartbeat file {hb_file}: {e}")

        print("-" * 50)
        print(f"Summary: {active_count} ACTIVE, {stale_count} STALE (or Unknown)")
        print("-" * 50)

# Add this function OUTSIDE of all classes, before the "if __name__ == '__main__':" section

def run_single_account(account_name):
    """Loads config and runs the EA for a single specified account."""
    config_file = 'accounts_config.json'
    account_config = None
    print(f"Attempting to run in single-account mode for: {account_name}")

    # Load the master config file to find the specific account
    try:
        with open(config_file, 'r') as f:
            accounts = json.load(f)

        # Find the specified account config
        for acc in accounts:
            # Match by name, case-insensitive comparison might be safer
            if acc.get('name', '').lower() == account_name.lower():
                account_config = acc
                break

        if not account_config:
            print(f"ERROR: Account '{account_name}' not found in configuration file '{config_file}'")
            sys.exit(1)

        print(f"Found configuration for account '{account_name}'. Starting EA...")
        # Create and run the EA instance for this account
        ea = PipSecureEA(account_config)
        ea.run() # This handles connect, loop, disconnect

    except FileNotFoundError:
        print(f"ERROR: Configuration file '{config_file}' not found.")
        create_sample_config()
        sys.exit(1)
    except json.JSONDecodeError:
        print(f"ERROR: Invalid JSON format in configuration file '{config_file}'.")
        sys.exit(1)
    except KeyboardInterrupt:
        # The EA's run method should handle this, but we add a message here too.
        print(f"\nMonitoring stopped by user for account '{account_name}'.")
    except Exception as e:
        print(f"ERROR during single account execution for '{account_name}': {e}")
        import traceback
        traceback.print_exc() # Print detailed traceback for debugging
        sys.exit(1)


def create_sample_config():
    """Create sample configuration file"""
    sample_config = [
        {
            "name": "XM_Demo", # Use descriptive names
            "login": 98509933,
            "password": "@Xmm232425",
            "server": "XMGlobal-MT5 5",
            "terminal_path": "C:/Program Files/XM Global MT5/terminal64.exe"
        },
        {
            "name": "TNFX_Demo",
            "login": 549357,
            "password": "@Tnf232425",
            "server": "TNFX-Demo",
            "terminal_path": "C:/Program Files/TNFX Ltd MetaTrader 5 Terminal/terminal64.exe"
        }
    ]
    config_file = 'accounts_config.json'
    try:
        with open(config_file, 'w') as f:
            json.dump(sample_config, f, indent=4)
        print(f"\nCreated sample configuration file: {config_file}")
        print("IMPORTANT: Please EDIT this file with your correct account details and terminal paths.")
    except Exception as e:
        print(f"\nERROR: Could not create sample config file {config_file}: {e}")


def check_ea_status(max_age_minutes=5):
    """
    Checks EA status based on heartbeat files found in the 'heartbeats' directory.
    """
    import glob

    heartbeat_dir = 'heartbeats'
    print(f"\n--- EA Heartbeat Status Check (Stale if > {max_age_minutes} minutes old) ---")
    if not os.path.exists(heartbeat_dir) or not os.path.isdir(heartbeat_dir):
        print(f"Heartbeat directory '{heartbeat_dir}' not found.")
        print("-" * 50)
        return

    heartbeat_files = glob.glob(os.path.join(heartbeat_dir, '*_heartbeat.txt'))
    if not heartbeat_files:
        print("No heartbeat files found.")
        print("-" * 50)
        return

    current_time = datetime.now()
    print(f"Current time: {current_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("-" * 50)

    stale_count = 0
    active_count = 0

    for hb_file in sorted(heartbeat_files):
        try:
            account_name = os.path.basename(hb_file).replace('_heartbeat.txt', '')
            monitor = HeartbeatMonitor(account_name, heartbeat_dir=heartbeat_dir) # Pass dir just in case

            last_heartbeat = monitor.get_last_heartbeat()
            if last_heartbeat is None:
                print(f"Account: {account_name:<20} | Status: UNKNOWN (No valid heartbeat data)")
                continue

            age = current_time - last_heartbeat
            age_minutes = age.total_seconds() / 60

            if monitor.is_stale(max_age_minutes):
                status = "STALE"
                stale_count += 1
            else:
                status = "ACTIVE"
                active_count += 1

            print(f"Account: {account_name:<20} | Status: {status:<7} | Last Beat: {last_heartbeat.strftime('%Y-%m-%d %H:%M:%S')} ({age_minutes:.1f} min ago)")

        except Exception as e:
            print(f"Error processing heartbeat file {hb_file}: {e}")

    print("-" * 50)
    print(f"Summary: {active_count} ACTIVE, {stale_count} STALE (or Unknown)")
    print("-" * 50)
# ------------------------------------------------------------------------
# MAIN ENTRY POINT
# ------------------------------------------------------------------------

if __name__ == "__main__":
    # Ensure necessary directories exist if possible (logs, heartbeats)
    # Use exist_ok=True to avoid errors if directories already exist
    os.makedirs('logs', exist_ok=True)
    os.makedirs('heartbeats', exist_ok=True)

    # Argument Parsing
    if len(sys.argv) > 1:
        command = sys.argv[1].lower()

        # --- Status Check Command ---
        if command == "--status":
            max_age = 5 # Default stale threshold
            if len(sys.argv) > 2:
                 try:
                      max_age = int(sys.argv[2])
                 except ValueError:
                      print(f"Invalid minutes value: '{sys.argv[2]}'. Using default {max_age} minutes.")
            check_ea_status(max_age_minutes=max_age)

        # --- Single Account Mode Command ---
        # Expecting format: python multi_account_ea.py AccountName
        else:
            # Assume the argument is the account name
            account_name_to_run = sys.argv[1]
            run_single_account(account_name_to_run)

    # --- Multi-Account Mode (Default) ---
    else:
        # No arguments provided, run in multi-account mode using MultiAccountMonitor
        print("No specific account name provided. Running in multi-account mode...")
        monitor = MultiAccountMonitor() # Loads config from 'accounts_config.json' by default
        monitor.run()

# --- END OF FILE multi_account_ea.py ---