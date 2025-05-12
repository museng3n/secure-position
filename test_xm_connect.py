# --- test_xm_connect.py ---
import MetaTrader5 as mt5
import time
import sys

# --- === Enter your XM credentials EXACTLY here === ---
xm_login = 98509933         # Replace with your actual XM MT5 Login ID
xm_password = "@Xmm232425"  # Replace with your actual XM MT5 Password
xm_server = "XMGlobal-MT5 5" # Replace with the exact XM Server name
# Use a raw string (r"...") for Windows paths to handle backslashes correctly
xm_terminal_path = r"C:/Program Files/XM Global MT5/terminal64.exe"
# --- ============================================ ---

print("--- Testing XM Connection ---")
print(f"Login: {xm_login}")
print(f"Server: {xm_server}")
print(f"Password: {'*' * len(xm_password)}") # Hide password in output
print(f"Terminal Path: {xm_terminal_path}")
print("-" * 30)

# Attempt initialization
if not mt5.initialize(path=xm_terminal_path,
                      login=xm_login,
                      password=xm_password,
                      server=xm_server,
                      timeout=20000): # Increased timeout just in case
    print(f"Initialize failed, error code = {mt5.last_error()}")
    mt5.shutdown()
    sys.exit(1) # Exit if failed

print("Initialization successful!")

# Check login state
if not mt5.account_info():
    print(f"Failed to get account info after initialize. Error code = {mt5.last_error()}")
    mt5.shutdown()
    sys.exit(1)

print("Successfully logged in.")
print("Account Info:", mt5.account_info())

# Shutdown
mt5.shutdown()
print("Connection closed successfully.")
print("-" * 30)
print("Test Completed.")
# --- End of test_xm_connect.py ---