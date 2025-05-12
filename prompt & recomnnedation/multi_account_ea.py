import MetaTrader5 as mt5
import time
from datetime import datetime, timedelta
import logging
from logging.handlers import TimedRotatingFileHandler
import os
import json
import sys
from multiprocessing import Process
import types

# ------------------------------------------------------------------------
# CORE PipSecureEA CLASS - Used by both solutions
# ------------------------------------------------------------------------

import MetaTrader5 as mt5
import time
from datetime import datetime, timedelta
import logging
from logging.handlers import TimedRotatingFileHandler
import os
import json
import sys
from multiprocessing import Process
# import types # This import seems unused, can likely be removed

# ------------------------------------------------------------------------
# CORE PipSecureEA CLASS - Used by both solutions
# ------------------------------------------------------------------------

class PipSecureEA:  # <--- Class definition starts here (no indent)

    # --- Methods MUST be indented below this line ---

    # Keep your original __init__, setup_logging, connect, disconnect, get_pip_multiplier, initialize_heartbeat here, indented like this:
    def __init__(self, account_config): # <--- Indented by 4 spaces
        # Account configuration
        self.account_config = account_config
        self.account_name = account_config.get('name', 'Unknown')

        # Define pip value multipliers for different currency pairs
        self.pip_multipliers = {
            'JPY': 0.01, 'OIL': 0.01, 'XAU': 0.01, 'US30': 1.0,
            'US100': 1.0, 'JP225': 1.0, 'GER40': 1.0, 'UK100': 1.0,
            'FRA40': 1.0, 'AUS200': 1.0, 'ESP35': 1.0, 'EUSTX50': 1.0,
            'DEFAULT': 0.0001
        }
        # Set to track positions that have already been secured
        self.secured_positions = set()
        # Dictionary to track position groups (might need initialization if used before identify_position_groups)
        # self.position_groups = {} # Original __init__ likely had this or similar
        # Parameters for grouping positions
        self.time_proximity_threshold = 5  # seconds
        self.price_proximity_threshold = 10  # pips (points for indices based on multiplier)

        # Setup logging and heartbeat
        self.setup_logging()
        self.initialize_heartbeat()
        # Add any other initializations from your original __init__

    # --- Now the methods you provided, correctly indented ---

    def log_key_event(self, event_type, message): # <--- Indented (Ln 29 in your paste)
        """Log key events to a separate file, including account name"""
        try:
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            log_line = f"[{timestamp}] [{self.account_name}] [{event_type}] {message}\n"
            # Use 'a+' mode to create the file if it doesn't exist
            with open('key_events.log', 'a+') as f:
                f.write(log_line)
        except Exception as e:
            self.logger.error(f"Error writing to key events log: {str(e)}")

    # --- Add your original setup_logging, connect, disconnect, get_pip_multiplier, initialize_heartbeat methods here, correctly indented ---
    # Example structure:
    def setup_logging(self): # <--- Indented
        log_dir = f'logs/{self.account_name}'
        # ... rest of setup_logging code indented further ...
        pass # Placeholder

    def initialize_heartbeat(self): # <--- Indented
        self.heartbeat = HeartbeatMonitor(self.account_name)
        pass # Placeholder

    def connect(self): # <--- Indented
        # ... connect code ...
        pass # Placeholder - Add your original connect code here

    def disconnect(self): # <--- Indented
        # ... disconnect code ...
        pass # Placeholder - Add your original disconnect code here

    def get_pip_multiplier(self, symbol): # <--- Indented
        # Return appropriate pip multiplier based on currency pair
        # Check specific keys first
        for key in self.pip_multipliers:
            if key != 'DEFAULT' and key in symbol:
                 # Check if 'US100' is in 'US100Cash' -> True
                 # Check if 'JPY' is in 'USDJPY' -> True
                return self.pip_multipliers[key]
        # Fallback to JPY check (if symbol ends with JPY)
        if symbol.endswith('JPY'):
             return self.pip_multipliers['JPY']
        # Default for others
        return self.pip_multipliers['DEFAULT']
        # pass # Placeholder - Add your original get_pip_multiplier code here

    # --- Continue with the methods from your paste, indented ---

    def secure_position(self, position, reason="TP1"): # <--- Indented (Ln 40 area in paste)
        """
        Secure position by moving SL to entry.
        Logs attempt, success/failure to main log and key_events.log.
        """
        entry_price = position.price_open
        ticket = position.ticket
        symbol = position.symbol

        pip_mult = self.get_pip_multiplier(symbol)
        # Adjust threshold slightly - use point value directly for indices maybe?
        # For a 1.0 multiplier, 0.1 means 0.1 points. Might be too tight?
        # Let's use 1 point as threshold for indices/non-forex:
        sl_threshold = pip_mult if pip_mult >= 1.0 else pip_mult * 1 # Use 1 pip/point threshold
        # Or simply use a small absolute value like 0.00001 for Forex?
        # Let's stick to pip_mult * 0.5 (half a pip/point) for flexibility
        sl_threshold = pip_mult * 0.5

        # Ensure SL is not zero before comparing
        if position.sl != 0 and abs(position.sl - entry_price) < sl_threshold:
            # self.logger.info(f"Position {ticket} already secured at entry (SL: {position.sl}, Entry: {entry_price})") # Reduce noise
            self.secured_positions.add(ticket)
            return True

        self.logger.info(f"[TARGET] Attempting to secure {symbol} (Ticket: {ticket}, Reason: {reason}) - Set SL to entry: {entry_price}")

        position_check = mt5.positions_get(ticket=ticket)
        if not position_check:
            self.logger.error(f"Position {ticket} no longer exists, cannot secure.")
            self.log_key_event("SECURE_FAIL", f"Ticket: {ticket}, Symbol: {symbol}, Reason: Position closed before securing")
            return False

        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "position": ticket,
            "symbol": symbol,
            "sl": entry_price,
            "tp": position.tp,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC
        }

        max_retries = 3
        last_result = None # Keep track of the last result
        for attempt in range(max_retries):
            try:
                result = mt5.order_send(request)
                last_result = result # Store the last result

                if result is None:
                    error_desc = mt5.last_error()
                    self.logger.error(f"Attempt {attempt + 1}/{max_retries}: order_send failed for {ticket} (None returned). Error: {error_desc}")
                    if attempt < max_retries - 1: time.sleep(1)
                    continue

                if result.retcode == mt5.TRADE_RETCODE_DONE:
                    self.logger.info(f"[SUCCESS] Secured position {ticket} ({symbol}). SL set to entry: {entry_price}")
                    self.log_key_event("SECURE_SUCCESS", f"Ticket: {ticket}, Symbol: {symbol}, Reason: {reason}, SL set to: {entry_price}")
                    self.secured_positions.add(ticket)
                    return True
                else:
                    self.logger.error(f"Attempt {attempt + 1}/{max_retries}: Failed to secure {ticket}. Retcode: {result.retcode}, Comment: {getattr(result, 'comment', 'N/A')}")
                    if result.retcode in [mt5.TRADE_RETCODE_INVALID_STOPS, mt5.TRADE_RETCODE_TRADE_DISABLED, mt5.TRADE_RETCODE_MARKET_CLOSED, 4756]: # Added ORDER_FROZEN
                         self.logger.warning(f"Non-retryable error ({result.retcode}) for {ticket}, stopping attempts.")
                         break
                    if attempt < max_retries - 1: time.sleep(1)

            except Exception as e:
                self.logger.error(f"Exception during order_send for {ticket} (Attempt {attempt + 1}): {str(e)}")
                if attempt < max_retries - 1: time.sleep(1)

        # After loop
        fail_reason = f"Failed after {max_retries} attempts."
        if last_result:
             fail_reason += f" Last Code: {last_result.retcode}, Last Comment: {getattr(last_result, 'comment', 'N/A')}"
        else:
             fail_reason += f" Last Error: {mt5.last_error()}"

        self.logger.error(f"[FAILURE] Failed to secure position {ticket} ({symbol}). {fail_reason}")
        self.log_key_event("SECURE_FAIL", f"Ticket: {ticket}, Symbol: {symbol}, Reason: {reason}, {fail_reason}")
        return False

    # --- Add your original identify_position_groups, get_position_index_in_group, identify_pending_orders, find_corresponding_pending_orders methods here, correctly indented ---
    # Example structure:
    def identify_position_groups(self): # <--- Indented
         # ... code ...
         pass # Placeholder - Add your original code

    def get_position_index_in_group(self, position, group): # <--- Indented
         # ... code ...
         pass # Placeholder - Add your original code

    def identify_pending_orders(self): # <--- Indented
         # ... code ...
         pass # Placeholder - Add your original code

    def find_corresponding_pending_orders(self, position_group): # <--- Indented
         # ... code ...
         pass # Placeholder - Add your original code


    def delete_pending_orders(self, orders, reason="TP1 Hit"): # <--- Indented (Ln 109 in paste)
        """
        Deletes a list of pending orders. Logs attempts and outcomes.
        Logs summary to key_events.log.
        """
        if not orders:
            return 0
        # ... rest of delete_pending_orders code indented further ...
        deleted_count = 0
        failed_tickets = []
        order_details = [] # For key event log

        symbol = orders[0].symbol if orders else "UnknownSymbol"
        self.logger.info(f"Attempting to delete {len(orders)} pending orders for {symbol} (Reason: {reason})")

        for order in orders:
            order_details.append(f"Ticket:{order.ticket} Price:{order.price_open}")
            request = {
                "action": mt5.TRADE_ACTION_REMOVE,
                "order": order.ticket,
                "comment": f"PipSecureEA: {reason}"
            }
            result = mt5.order_send(request)
            # ... (rest of loop) ...
            if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                 self.logger.info(f"Successfully deleted pending order {order.ticket} ({symbol})")
                 deleted_count += 1
            else:
                 error = mt5.last_error()
                 retcode = result.retcode if result else "N/A"
                 comment = getattr(result, 'comment', 'N/A')
                 self.logger.error(f"Failed to delete pending order {order.ticket} ({symbol}): Retcode={retcode}, Comment={comment}, LastError={error}")
                 failed_tickets.append(str(order.ticket)) # Ensure ticket is string for join

        if deleted_count > 0:
             self.log_key_event("PENDING_DELETE_SUCCESS", f"Symbol: {symbol}, Reason: {reason}, Deleted: {deleted_count}/{len(orders)}, Details: [{'; '.join(order_details)}]")
        if failed_tickets:
             # Join failed tickets into a string
             failed_tickets_str = ', '.join(failed_tickets)
             self.log_key_event("PENDING_DELETE_FAIL", f"Symbol: {symbol}, Reason: {reason}, Failed to delete: {len(failed_tickets)}/{len(orders)}, Tickets: [{failed_tickets_str}]")

        return deleted_count


    def secure_second_price_positions(self, first_price_group, first_price_entry): # <--- Indented (Ln 152 in paste)
        """
        Secures positions believed to be from a second price level by setting their SL
        to the entry price of the *first* price level. Logs attempts and outcomes.
        Logs success/failure to key_events.log.
        """
        if not first_price_group or not first_price_entry:
            self.logger.warning("secure_second_price_positions called with empty group or no entry price.")
            return 0
        # ... rest of secure_second_price_positions code indented further ...
        sample_position = first_price_group[0]
        symbol = sample_position.symbol
        position_type = sample_position.type
        first_price_tickets = {pos.ticket for pos in first_price_group}

        self.logger.info(f"Searching for second price positions for {symbol} (Type: {position_type}) to secure at first price entry: {first_price_entry}")

        all_positions = mt5.positions_get(symbol=symbol)
        # ... (rest of function) ...
        if not all_positions:
             self.logger.info(f"No other positions found for {symbol}.")
             return 0

        potential_second_price = [
            pos for pos in all_positions
            if pos.type == position_type and pos.ticket not in first_price_tickets
        ]

        if not potential_second_price:
            self.logger.info(f"No potential second price positions found for {symbol} to secure.")
            return 0

        self.logger.info(f"Found {len(potential_second_price)} potential second price positions for {symbol}. Attempting to secure them at {first_price_entry}.")

        secured_count = 0
        last_result = None # Track last result for logging
        for position in potential_second_price:
            ticket = position.ticket
            if ticket in self.secured_positions:
                continue

            request = {
                "action": mt5.TRADE_ACTION_SLTP, "position": ticket, "symbol": symbol,
                "sl": first_price_entry, "tp": position.tp,
                "type_time": mt5.ORDER_TIME_GTC, "type_filling": mt5.ORDER_FILLING_IOC
            }
            self.logger.info(f"[TARGET RULE 2] Attempting to secure second price pos {ticket} ({symbol}) - Set SL to FIRST price entry: {first_price_entry}")

            result = mt5.order_send(request)
            last_result = result # Store last result

            if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                self.logger.info(f"[SUCCESS RULE 2] Secured second price position {ticket} ({symbol}). SL set to FIRST price entry: {first_price_entry}")
                self.log_key_event("SECURE_SECOND_PRICE_SUCCESS", f"Ticket: {ticket}, Symbol: {symbol}, SL set to First Price Entry: {first_price_entry}")
                self.secured_positions.add(ticket)
                secured_count += 1
            else:
                error = mt5.last_error()
                retcode = result.retcode if result else "N/A"
                comment = getattr(result, 'comment', 'N/A') if result else 'N/A'
                self.logger.error(f"[FAILURE RULE 2] Failed to secure second price position {ticket} ({symbol}). Retcode={retcode}, Comment={comment}, LastError={error}")
                self.log_key_event("SECURE_SECOND_PRICE_FAIL", f"Ticket: {ticket}, Symbol: {symbol}, Failed to set SL to First Price Entry: {first_price_entry}. Error: Retcode={retcode}")

        self.logger.info(f"Finished attempting to secure second price positions for {symbol}. Secured: {secured_count}/{len(potential_second_price)}.")
        return secured_count


    def check_positions(self): # <--- Indented (Ln 235 in paste)
        """
        Checks positions, applies securing logic with reduced logging verbosity.
        Focuses logging on events and potential actions.
        """
        try:
            start_time = time.time()
            # ... rest of check_positions code indented further ...

            if not mt5.terminal_info():
                # ... (connection handling) ...
                pass

            positions = mt5.positions_get()
            # ... (position handling, looping, logic) ...
            # Ensure all code inside this method is indented correctly relative to this def line
            pass # Placeholder

        except Exception as e:
            self.logger.error(f"Critical error in check_positions main loop: {str(e)}", exc_info=True)

    # --- Add your original run method here, correctly indented ---
    def run(self): # <--- Indented
        # ... run code ...
        pass # Placeholder - Add your original run code here


# ------------------------------------------------------------------------
# HEARTBEAT MONITORING SYSTEM (Should be OUTSIDE PipSecureEA class)
# ------------------------------------------------------------------------
class HeartbeatMonitor: # <--- No indent
    # ... HeartbeatMonitor methods indented inside this class ...
    def __init__(self, account_name, heartbeat_dir='heartbeats'): #<--- Indented
        #...
        pass
    def update_heartbeat(self): #<--- Indented
        #...
        pass
    # etc.

# ------------------------------------------------------------------------
# SOLUTION 1: MULTI-ACCOUNT MONITOR (OUTSIDE PipSecureEA class)
# ------------------------------------------------------------------------
class MultiAccountMonitor: # <--- No indent
    # ... MultiAccountMonitor methods indented inside this class ...
    def __init__(self, config_file='accounts_config.json'): #<--- Indented
        #...
        pass
    # etc.

# ------------------------------------------------------------------------
# SOLUTION 2: SINGLE-ACCOUNT SCRIPTS (These are functions, OUTSIDE classes)
# ------------------------------------------------------------------------
def run_single_account(account_name): # <--- No indent
    # ... code ...
    pass

def create_sample_config(): # <--- No indent
    # ... code ...
    pass

# ------------------------------------------------------------------------
# UTILITY FUNCTION TO CHECK EA STATUS (Function, OUTSIDE classes)
# ------------------------------------------------------------------------
def check_ea_status(): # <--- No indent
    # ... code ...
    pass

# ------------------------------------------------------------------------
# ENTRY POINTS (Top level, OUTSIDE classes/functions)
# ------------------------------------------------------------------------
if __name__ == "__main__": # <--- No indent
    # ... code ...
    pass


# ------------------------------------------------------------------------
# HEARTBEAT MONITORING SYSTEM
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
            os.makedirs(heartbeat_dir)
            
    def update_heartbeat(self):
        """Update the heartbeat file with current timestamp"""
        try:
            current_time = datetime.now()
            with open(self.heartbeat_file, 'w') as f:
                f.write(f"Last active: {current_time.strftime('%Y-%m-%d %H:%M:%S')}")
        except Exception as e:
            # Fail silently - this is non-critical functionality
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
            return True
            
        current_time = datetime.now()
        age = current_time - last_heartbeat
        return age.total_seconds() / 60 > max_age_minutes


# ------------------------------------------------------------------------
# SOLUTION 1: MULTI-ACCOUNT MONITOR (ONE SCRIPT FOR ALL ACCOUNTS)
# ------------------------------------------------------------------------

class MultiAccountMonitor:
    def __init__(self, config_file='accounts_config.json'):
        self.config_file = config_file
        self.setup_logging()
        self.load_configs()
        
    def setup_logging(self):
        if not os.path.exists('logs'):
            os.makedirs('logs')
            
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                TimedRotatingFileHandler('logs/multi_account_monitor.log', when='midnight', interval=1, backupCount=7),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger('MultiAccountMonitor')
        
    def load_configs(self):
        try:
            with open(self.config_file, 'r') as f:
                self.accounts = json.load(f)
            self.logger.info(f"Loaded {len(self.accounts)} account configurations")
        except FileNotFoundError:
            self.logger.error(f"Config file {self.config_file} not found")
            self.create_sample_config()
            sys.exit(1)
        except json.JSONDecodeError:
            self.logger.error(f"Invalid JSON in config file {self.config_file}")
            sys.exit(1)
            
    def create_sample_config(self):
        sample_config = [
            {
                "name": "XM",
                "login": 98509933,
                "password": "@Xmm232425",
                "server": "XMGlobal-MT5 5",
                "terminal_path": "C:/Program Files/XM Global MT5/terminal64.exe"
            },
            {
                "name": "TNFX",
                "login": 549357,
                "password": "@Tnf232425",
                "server": "TNFX-Demo",
                "terminal_path": "C:/Program Files/TNFX Ltd MetaTrader 5 Terminal/terminal64.exe"
            }
        ]
        
        with open(self.config_file, 'w') as f:
            json.dump(sample_config, f, indent=4)
            
        self.logger.info(f"Created sample config file at {self.config_file}")
        self.logger.info("Please edit this file with your account details and run the script again")
        
    def process_account(self, account_config):
        ea = PipSecureEA(account_config)
        if ea.connect():
            try:
                ea.run()
            finally:
                ea.disconnect()
        
    def run(self):
        self.logger.info("Starting Multi-Account Monitor")
        
        processes = []
        for account_config in self.accounts:
            p = Process(target=self.process_account, args=(account_config,))
            processes.append(p)
            p.start()
            self.logger.info(f"Started process for account {account_config['name']}")
            
        try:
            # Wait for all processes to complete (which they never should)
            for p in processes:
                p.join()
        except KeyboardInterrupt:
            self.logger.info("Received interrupt, terminating all processes")
            for p in processes:
                p.terminate()
                p.join()


# ------------------------------------------------------------------------
# SOLUTION 2: SINGLE-ACCOUNT SCRIPTS (SEPARATE SCRIPT FOR EACH ACCOUNT)
# ------------------------------------------------------------------------

def run_single_account(account_name):
    # Load the specific account config from the master config file
    try:
        with open('accounts_config.json', 'r') as f:
            accounts = json.load(f)
            
        # Find the specified account
        account_config = None
        for acc in accounts:
            if acc['name'] == account_name:
                account_config = acc
                break
                
        if not account_config:
            print(f"Account {account_name} not found in configuration")
            sys.exit(1)
            
        # Run the EA for this account
        ea = PipSecureEA(account_config)
        if ea.connect():
            try:
                ea.run()
            finally:
                ea.disconnect()
                
    except FileNotFoundError:
        print("Config file accounts_config.json not found")
        create_sample_config()
        sys.exit(1)
    except json.JSONDecodeError:
        print("Invalid JSON in config file accounts_config.json")
        sys.exit(1)
    except KeyboardInterrupt:
        print(f"Monitoring for account {account_name} stopped by user")


def create_sample_config():
    sample_config = [
        {
            "name": "XM",
            "login": 98509933,
            "password": "@Xmm232425",
            "server": "XMGlobal-MT5 5",
            "terminal_path": "C:/Program Files/XM Global MT5/terminal64.exe"
        },
        {
            "name": "TNFX",
            "login": 549357,
            "password": "@Tnf232425",
            "server": "TNFX-Demo",
            "terminal_path": "C:/Program Files/TNFX Ltd MetaTrader 5 Terminal/terminal64.exe"
        }
    ]
    
    with open('accounts_config.json', 'w') as f:
        json.dump(sample_config, f, indent=4)
        
    print(f"Created sample config file at accounts_config.json")
    print("Please edit this file with your account details and run the script again")


# ------------------------------------------------------------------------
# UTILITY FUNCTION TO CHECK EA STATUS
# ------------------------------------------------------------------------

def check_ea_status():
    """
    Utility function to check EA status based on heartbeat files.
    Can be run from a separate monitoring process/script.
    """
    import glob
    
    heartbeat_dir = 'heartbeats'
    if not os.path.exists(heartbeat_dir):
        print("No heartbeat directory found")
        return
        
    heartbeat_files = glob.glob(os.path.join(heartbeat_dir, '*_heartbeat.txt'))
    current_time = datetime.now()
    
    print(f"Checking EA status at {current_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("-" * 50)
    
    for hb_file in heartbeat_files:
        account_name = os.path.basename(hb_file).replace('_heartbeat.txt', '')
        monitor = HeartbeatMonitor(account_name)
        
        last_heartbeat = monitor.get_last_heartbeat()
        if last_heartbeat is None:
            print(f"Account {account_name}: No heartbeat data")
            continue
            
        age_minutes = (current_time - last_heartbeat).total_seconds() / 60
        status = "STALE" if age_minutes > 5 else "ACTIVE"
        
        print(f"Account {account_name}: {status}, Last active: {last_heartbeat.strftime('%Y-%m-%d %H:%M:%S')} ({age_minutes:.1f} min ago)")
    
    print("-" * 50)


# ------------------------------------------------------------------------
# ENTRY POINTS FOR BOTH SOLUTIONS
# ------------------------------------------------------------------------

if __name__ == "__main__":
    # Check command line arguments to determine which mode to run
    if len(sys.argv) > 1:
        # Special case for status check
        if sys.argv[1] == "--status":
            check_ea_status()
        else:
            # If we have an argument, run in single-account mode
            account_name = sys.argv[1]
            run_single_account(account_name)
    else:
        # No arguments, run in multi-account mode
        monitor = MultiAccountMonitor()
        monitor.run()
