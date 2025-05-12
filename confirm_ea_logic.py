# --- START OF FILE confirm_ea_logic.py ---

import unittest
from unittest.mock import patch, MagicMock, call, ANY
import sys
import os
import logging
from datetime import datetime, timezone
import time
from types import SimpleNamespace
import uuid

# IMPORTANT: Add the directory containing multi_account_ea.py to the Python path
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.insert(0, script_dir)


# Import the class we want to test
try:
    # This line must be indented under the try:
    from multi_account_ea import PipSecureEA
    # If nothing else needs to be in the 'try' block right now, add 'pass'
    # pass # Optional here as except block follows immediately
except ImportError as e:
    # This block must be indented
    print(f"Error importing PipSecureEA. Make sure multi_account_ea.py is accessible.")
    print(f"Details: {e}")
    sys.exit(1)
except NameError as ne:
     # This block must be indented
     print(f"NameError during import setup: {ne}.")
     sys.exit(1)
# Ensure this comment and subsequent lines have NO indentation
# --- Helper Functions/Classes for Mocking ---

def create_mock_position(ticket, symbol, p_type, price_open, sl, tp, price_current, p_time, volume=0.01, time_msc=0, time_update=0, time_update_msc=0, **kwargs):
    """Creates a mock object mimicking an MT5 Position."""
    pos = SimpleNamespace()
    pos.ticket = ticket
    pos.symbol = symbol
    pos.type = p_type # 0 for Buy, 1 for Sell
    pos.price_open = price_open
    pos.sl = sl
    pos.tp = tp
    pos.price_current = price_current
    pos.time = p_time # Use Unix timestamp
    pos.time_msc = time_msc
    pos.time_update = time_update
    pos.time_update_msc = time_update_msc
    pos.volume = volume
    pos.comment = kwargs.get('comment', '')
    pos.magic = kwargs.get('magic', 0)
    return pos

def create_mock_order(ticket, symbol, o_type, price_open, sl, tp, time_setup, state, volume=0.01, **kwargs):
    """Creates a mock object mimicking an MT5 Order."""
    order = SimpleNamespace()
    order.ticket = ticket
    order.symbol = symbol
    order.type = o_type # e.g., ORDER_TYPE_BUY_LIMIT
    order.price_open = price_open
    order.sl = sl
    order.tp = tp
    order.time_setup = time_setup # Use Unix timestamp
    order.state = state # e.g., ORDER_STATE_PLACED
    order.volume = volume
    order.comment = kwargs.get('comment', '')
    order.magic = kwargs.get('magic', 0)
    return order

def create_mock_symbol_info(symbol, digits=5, **kwargs):
    """Creates a mock object mimicking SymbolInfo."""
    info = SimpleNamespace()
    info.name = symbol
    info.digits = digits
    for k, v in kwargs.items():
        setattr(info, k, v)
    return info

# --- Main Test Class ---
MT5_PATCH_TARGET = 'multi_account_ea.mt5'

class TestPipSecureEALogic(unittest.TestCase):

    # Class Attribute Constants
    ORDER_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1
    TRADE_ACTION_SLTP = 2
    TRADE_ACTION_REMOVE = 1
    ORDER_STATE_PLACED = 1
    ORDER_STATE_STARTED = 0
    TRADE_RETCODE_DONE = 10009
    ORDER_TYPE_BUY_LIMIT = 2
    ORDER_TYPE_BUY_STOP = 3
    ORDER_TYPE_SELL_LIMIT = 4
    ORDER_TYPE_SELL_STOP = 5
    ORDER_TYPE_BUY_STOP_LIMIT = 6
    ORDER_TYPE_SELL_STOP_LIMIT = 7

    @classmethod
    def setUpClass(cls):
        """Runs ONCE before all tests in this class."""
        os.makedirs('logs', exist_ok=True)
        cls.key_log_file_base = os.path.join('logs', 'key_events') # Base name

    def setUp(self):
        """Called before EACH test method."""
        # Unique log file setup
        self.test_run_id = str(uuid.uuid4())
        # Use the base name + unique ID
        self.key_log_file = f"{TestPipSecureEALogic.key_log_file_base}_{self.test_run_id}.log"

        if os.path.exists(self.key_log_file):
            try: os.remove(self.key_log_file)
            except OSError as e: self.fail(f"Failed to remove old unique key log file '{self.key_log_file}' in setUp: {e}")

        # Mock MT5 Functions
        try:
            self.patcher_initialize = patch(f'{MT5_PATCH_TARGET}.initialize', return_value=True)
            self.patcher_shutdown = patch(f'{MT5_PATCH_TARGET}.shutdown')
            self.patcher_terminal_info = patch(f'{MT5_PATCH_TARGET}.terminal_info', return_value=MagicMock(connected=True))
            self.patcher_positions_get = patch(f'{MT5_PATCH_TARGET}.positions_get')
            self.patcher_orders_get = patch(f'{MT5_PATCH_TARGET}.orders_get')
            self.patcher_order_send = patch(f'{MT5_PATCH_TARGET}.order_send')
            self.patcher_symbol_info = patch(f'{MT5_PATCH_TARGET}.symbol_info')
            self.patcher_last_error = patch(f'{MT5_PATCH_TARGET}.last_error', return_value=(0, "Success"))

            self.mock_initialize = self.patcher_initialize.start()
            self.mock_shutdown = self.patcher_shutdown.start()
            self.mock_terminal_info = self.patcher_terminal_info.start()
            self.mock_positions_get = self.patcher_positions_get.start()
            self.mock_orders_get = self.patcher_orders_get.start()
            self.mock_order_send = self.patcher_order_send.start()
            self.mock_symbol_info = self.patcher_symbol_info.start()
            self.mock_last_error = self.patcher_last_error.start()

            # Patch constants using self.CONSTANTS
            patch(f'{MT5_PATCH_TARGET}.ORDER_TYPE_BUY', self.ORDER_TYPE_BUY, create=True).start()
            patch(f'{MT5_PATCH_TARGET}.ORDER_TYPE_SELL', self.ORDER_TYPE_SELL, create=True).start()
            patch(f'{MT5_PATCH_TARGET}.TRADE_ACTION_SLTP', self.TRADE_ACTION_SLTP, create=True).start()
            patch(f'{MT5_PATCH_TARGET}.TRADE_ACTION_REMOVE', self.TRADE_ACTION_REMOVE, create=True).start()
            patch(f'{MT5_PATCH_TARGET}.ORDER_STATE_PLACED', self.ORDER_STATE_PLACED, create=True).start()
            patch(f'{MT5_PATCH_TARGET}.ORDER_STATE_STARTED', self.ORDER_STATE_STARTED, create=True).start()
            patch(f'{MT5_PATCH_TARGET}.TRADE_RETCODE_DONE', self.TRADE_RETCODE_DONE, create=True).start()
            patch(f'{MT5_PATCH_TARGET}.ORDER_TYPE_BUY_LIMIT', self.ORDER_TYPE_BUY_LIMIT, create=True).start()
            patch(f'{MT5_PATCH_TARGET}.ORDER_TYPE_BUY_STOP', self.ORDER_TYPE_BUY_STOP, create=True).start()
            patch(f'{MT5_PATCH_TARGET}.ORDER_TYPE_SELL_LIMIT', self.ORDER_TYPE_SELL_LIMIT, create=True).start()
            patch(f'{MT5_PATCH_TARGET}.ORDER_TYPE_SELL_STOP', self.ORDER_TYPE_SELL_STOP, create=True).start()
            patch(f'{MT5_PATCH_TARGET}.ORDER_TYPE_BUY_STOP_LIMIT', self.ORDER_TYPE_BUY_STOP_LIMIT, create=True).start()
            patch(f'{MT5_PATCH_TARGET}.ORDER_TYPE_SELL_STOP_LIMIT', self.ORDER_TYPE_SELL_STOP_LIMIT, create=True).start()

        except AttributeError as ae:
             self.fail(f"AttributeError during patching setup: {ae}.")

        # Configure Mock Defaults
        self.mock_positions_get.return_value = []
        self.mock_orders_get.return_value = []
        self.mock_order_send.return_value = MagicMock(retcode=self.TRADE_RETCODE_DONE, comment="Mock Success")
        self.mock_symbol_info.side_effect = lambda symbol: create_mock_symbol_info(symbol, digits=5 if 'JPY' not in symbol else 3)

        # EA Instance
        self.test_account_config = {'name': 'TestConfirm', 'login': 12345}
        try:
            self.ea = PipSecureEA(self.test_account_config)
            # Monkey-patch log_key_event for this instance
            def unique_log_key_event(event_type, message):
                try:
                    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    os.makedirs('logs', exist_ok=True)
                    with open(self.key_log_file, 'a', encoding='utf-8') as f:
                        f.write(f"[{timestamp}] [{self.ea.account_name}] [{event_type}] {message}\n")
                except Exception as e_log:
                     print(f"ERROR writing to unique key events log '{self.key_log_file}': {str(e_log)}")
            self.ea.log_key_event = unique_log_key_event

        except Exception as e_init:
             self.fail(f"Failed to initialize PipSecureEA in setUp: {e_init}")

        # Reduce logging noise
        if hasattr(self.ea, 'logger'):
            self.ea.logger.setLevel(logging.WARNING)
        else: print("Warning: EA instance in setUp does not have 'logger' attribute.")

        # Reset internal state
        self.ea.secured_positions = set()
        self.ea.last_logged = {}


    def tearDown(self):
        """Called after EACH test method."""
        patch.stopall()
        # Clean up the unique log file
        if os.path.exists(self.key_log_file):
            try: os.remove(self.key_log_file)
            except OSError as e: print(f"Warning: Could not remove unique key log file '{self.key_log_file}' in tearDown: {e}")


    def _read_key_log_lines(self):
        if not os.path.exists(self.key_log_file): return []
        try:
            with open(self.key_log_file, 'r', encoding='utf-8') as f:
                return f.readlines()
        except Exception as e:
            print(f"Warning: Could not read key log file '{self.key_log_file}': {e}")
            return []

    # --- Test Cases ---
    # (test_01_... to test_07_... methods remain the same)
    # ...
    def test_01_tp1_secure_close_pips(self):
        """Rule 1: TP1 (grouped) is within 3 pips, should secure TP1 & sibling."""
        print("\nRunning Test: test_01_tp1_secure_close_pips")
        entry_price = 1.10000
        tp1_price = 1.10100
        tp2_price = 1.10200
        current_price = 1.10098
        pos_time1 = int(datetime.now(timezone.utc).timestamp())
        pos_time2 = pos_time1 + 1

        # --- FIX: Use self.CONSTANT ---
        mock_pos_tp1 = create_mock_position(ticket=101, symbol='EURUSD', p_type=self.ORDER_TYPE_BUY,
                                            price_open=entry_price, sl=1.09900, tp=tp1_price,
                                            price_current=current_price, p_time=pos_time1)
        mock_pos_tp2 = create_mock_position(ticket=102, symbol='EURUSD', p_type=self.ORDER_TYPE_BUY,
                                            price_open=entry_price, sl=1.09900, tp=tp2_price,
                                            price_current=current_price, p_time=pos_time2)
        self.mock_positions_get.return_value = [mock_pos_tp1, mock_pos_tp2]

        self.ea.check_positions()

        # --- FIX: Use self.CONSTANT ---
        expected_request_tp1 = {"action": self.TRADE_ACTION_SLTP, "position": 101, "symbol": 'EURUSD', "sl": entry_price, "tp": tp1_price, "comment": ANY}
        expected_request_tp2 = {"action": self.TRADE_ACTION_SLTP, "position": 102, "symbol": 'EURUSD', "sl": entry_price, "tp": tp2_price, "comment": ANY}
        self.assertEqual(self.mock_order_send.call_count, 2)
        self.mock_order_send.assert_has_calls([call(expected_request_tp1), call(expected_request_tp2)], any_order=True)
        self.assertIn(101, self.ea.secured_positions)
        self.assertIn(102, self.ea.secured_positions)
        key_log_lines = self._read_key_log_lines()
        self.assertEqual(len(key_log_lines), 1, f"Log content: {''.join(key_log_lines)}")
        self.assertTrue(any("[TP1_SECURED]" in line and "Position 101" in line for line in key_log_lines), f"Log content: {''.join(key_log_lines)}")


    def test_02_tp1_secure_80_percent(self):
        """Rule 1: TP1 (grouped) reached >80% distance, should secure TP1 & sibling."""
        print("\nRunning Test: test_02_tp1_secure_80_percent")
        entry_price = 1.20000
        tp1_price = 1.20500
        tp2_price = 1.20800
        current_price = 1.20410
        pos_time1 = int(datetime.now(timezone.utc).timestamp())
        pos_time2 = pos_time1 + 1

        # --- FIX: Use self.CONSTANT ---
        mock_pos_tp1 = create_mock_position(ticket=102, symbol='GBPUSD', p_type=self.ORDER_TYPE_BUY,
                                            price_open=entry_price, sl=1.19800, tp=tp1_price,
                                            price_current=current_price, p_time=pos_time1)
        mock_pos_tp1_sibling = create_mock_position(ticket=103, symbol='GBPUSD', p_type=self.ORDER_TYPE_BUY,
                                            price_open=entry_price, sl=1.19800, tp=tp2_price,
                                            price_current=current_price, p_time=pos_time2)
        self.mock_positions_get.return_value = [mock_pos_tp1, mock_pos_tp1_sibling]

        self.ea.check_positions()

        # --- FIX: Use self.CONSTANT ---
        expected_request_tp1 = {"action": self.TRADE_ACTION_SLTP, "position": 102, "symbol": 'GBPUSD', "sl": entry_price, "tp": tp1_price, "comment": ANY}
        expected_request_tp2 = {"action": self.TRADE_ACTION_SLTP, "position": 103, "symbol": 'GBPUSD', "sl": entry_price, "tp": tp2_price, "comment": ANY}
        self.assertEqual(self.mock_order_send.call_count, 2)
        self.mock_order_send.assert_has_calls([call(expected_request_tp1), call(expected_request_tp2)], any_order=True)
        self.assertIn(102, self.ea.secured_positions)
        self.assertIn(103, self.ea.secured_positions)
        key_log_lines = self._read_key_log_lines()
        self.assertEqual(len(key_log_lines), 1, f"Log content: {''.join(key_log_lines)}")
        self.assertTrue(any("[TP1_SECURED]" in line and "Position 102" in line for line in key_log_lines), f"Log content: {''.join(key_log_lines)}")


    def test_03_group_secure_tp2_after_tp1(self):
        """Rule 2: TP1 hit secures TP1, should also secure TP2 in same group."""
        print("\nRunning Test: test_03_group_secure_tp2_after_tp1")
        entry_price = 0.95000
        tp1_price = 0.95200
        tp2_price = 0.95500
        current_price = 0.95199
        pos_time1 = int(datetime.now(timezone.utc).timestamp())
        pos_time2 = pos_time1 + 2

        # --- FIX: Use self.CONSTANT ---
        mock_pos_tp1 = create_mock_position(ticket=201, symbol='USDCHF', p_type=self.ORDER_TYPE_BUY,
                                            price_open=entry_price, sl=0.94800, tp=tp1_price,
                                            price_current=current_price, p_time=pos_time1)
        mock_pos_tp2 = create_mock_position(ticket=202, symbol='USDCHF', p_type=self.ORDER_TYPE_BUY,
                                            price_open=entry_price, sl=0.94800, tp=tp2_price,
                                            price_current=current_price, p_time=pos_time2)
        self.mock_positions_get.return_value = [mock_pos_tp1, mock_pos_tp2]
        self.mock_orders_get.return_value = []

        self.ea.check_positions()

        # --- FIX: Use self.CONSTANT ---
        expected_req_tp1 = {"action": self.TRADE_ACTION_SLTP, "position": 201, "sl": entry_price, "tp": tp1_price, "symbol": 'USDCHF', "comment": ANY}
        expected_req_tp2 = {"action": self.TRADE_ACTION_SLTP, "position": 202, "sl": entry_price, "tp": tp2_price, "symbol": 'USDCHF', "comment": ANY}
        self.assertEqual(self.mock_order_send.call_count, 2)
        self.mock_order_send.assert_has_calls([call(expected_req_tp1), call(expected_req_tp2)], any_order=True)
        self.assertIn(201, self.ea.secured_positions)
        self.assertIn(202, self.ea.secured_positions)
        key_log_lines = self._read_key_log_lines()
        self.assertEqual(len(key_log_lines), 1, f"Log content: {''.join(key_log_lines)}")
        self.assertTrue(any("[TP1_SECURED]" in line and "Position 201" in line for line in key_log_lines), f"Log content: {''.join(key_log_lines)}")


    def test_04_rule1_delete_pending_orders(self):
        """Rule 3.1: TP1 (grouped) hit, second price pending -> DELETE pending."""
        print("\nRunning Test: test_04_rule1_delete_pending_orders")
        entry1 = 1.12000
        tp1_target = 1.12150
        tp2_target = 1.12300
        current = 1.12148
        time1 = int(datetime.now(timezone.utc).timestamp())
        time1_sibling = time1 + 1

        # --- FIX: Use self.CONSTANT ---
        mock_pos_tp1 = create_mock_position(ticket=301, symbol='EURUSD', p_type=self.ORDER_TYPE_BUY,
                                            price_open=entry1, sl=1.11900, tp=tp1_target,
                                            price_current=current, p_time=time1)
        mock_pos_tp1_sibling = create_mock_position(ticket=302, symbol='EURUSD', p_type=self.ORDER_TYPE_BUY,
                                            price_open=entry1, sl=1.11900, tp=tp2_target,
                                            price_current=current, p_time=time1_sibling)

        pending_entry = 1.11500
        pend_tp1 = 1.11800
        pend_tp2 = 1.11850
        time_setup_pending = time1 - 60
        # --- FIX: Use self.CONSTANT ---
        mock_pending1 = create_mock_order(ticket=901, symbol='EURUSD', o_type=self.ORDER_TYPE_BUY_LIMIT,
                                         price_open=pending_entry, sl=1.11400, tp=pend_tp1,
                                         time_setup=time_setup_pending, state=self.ORDER_STATE_PLACED)
        mock_pending2 = create_mock_order(ticket=902, symbol='EURUSD', o_type=self.ORDER_TYPE_BUY_LIMIT,
                                         price_open=pending_entry - 0.00010, sl=1.11400, tp=pend_tp2,
                                         time_setup=time_setup_pending + 1, state=self.ORDER_STATE_PLACED)

        self.mock_positions_get.return_value = [mock_pos_tp1, mock_pos_tp1_sibling]
        self.mock_orders_get.return_value = [mock_pending1, mock_pending2]

        self.ea.check_positions()

        # --- FIX: Use self.CONSTANT ---
        call_secure_tp1 = call({"action": self.TRADE_ACTION_SLTP, "position": 301, "sl": entry1, "tp": tp1_target, "symbol": 'EURUSD', "comment": ANY})
        call_secure_sibling = call({"action": self.TRADE_ACTION_SLTP, "position": 302, "sl": entry1, "tp": tp2_target, "symbol": 'EURUSD', "comment": ANY})
        call_delete_pend1 = call({"action": self.TRADE_ACTION_REMOVE, "order": 901, "comment": ANY})
        call_delete_pend2 = call({"action": self.TRADE_ACTION_REMOVE, "order": 902, "comment": ANY})
        self.assertEqual(self.mock_order_send.call_count, 4)
        self.mock_order_send.assert_has_calls([call_secure_tp1, call_secure_sibling, call_delete_pend1, call_delete_pend2], any_order=True)
        self.assertIn(301, self.ea.secured_positions)
        self.assertIn(302, self.ea.secured_positions)
        key_log_lines = self._read_key_log_lines()
        self.assertEqual(len(key_log_lines), 3, f"Log content: {''.join(key_log_lines)}")
        self.assertTrue(any("[TP1_SECURED]" in line and "Position 301" in line for line in key_log_lines), f"Log content: {''.join(key_log_lines)}")
        self.assertTrue(any("[PENDING_DELETED]" in line and "order 901" in line for line in key_log_lines), f"Log content: {''.join(key_log_lines)}")
        self.assertTrue(any("[PENDING_DELETED]" in line and "order 902" in line for line in key_log_lines), f"Log content: {''.join(key_log_lines)}")


    def test_05_rule2_secure_second_price_active(self):
        """Rule 3.2: TP1 (grouped) hit, second price active -> SECURE second at FIRST price entry."""
        print("\nRunning Test: test_05_rule2_secure_second_price_active")
        entry1 = 1.25000
        tp1_target = 1.25200
        tp1_sib_target = 1.25500
        current = 1.25198
        time1 = int(datetime.now(timezone.utc).timestamp())
        time1_sibling = time1 + 1

        # --- FIX: Use self.CONSTANT ---
        mock_pos_tp1 = create_mock_position(ticket=401, symbol='GBPUSD', p_type=self.ORDER_TYPE_BUY,
                                            price_open=entry1, sl=1.24800, tp=tp1_target,
                                            price_current=current, p_time=time1)
        mock_pos_tp1_sibling = create_mock_position(ticket=402, symbol='GBPUSD', p_type=self.ORDER_TYPE_BUY,
                                            price_open=entry1, sl=1.24800, tp=tp1_sib_target,
                                            price_current=current, p_time=time1_sibling)

        entry2 = 1.24500
        tp2_target1 = 1.24800
        tp2_target2 = 1.24900
        time2 = time1 + 120
        # --- FIX: Use self.CONSTANT ---
        mock_pos_sec1 = create_mock_position(ticket=501, symbol='GBPUSD', p_type=self.ORDER_TYPE_BUY,
                                            price_open=entry2, sl=1.24300, tp=tp2_target1,
                                            price_current=current, p_time=time2)
        mock_pos_sec2 = create_mock_position(ticket=502, symbol='GBPUSD', p_type=self.ORDER_TYPE_BUY,
                                            price_open=entry2, sl=1.24300, tp=tp2_target2,
                                            price_current=current, p_time=time2 + 1)

        self.mock_positions_get.return_value = [mock_pos_tp1, mock_pos_tp1_sibling, mock_pos_sec1, mock_pos_sec2]
        self.mock_orders_get.return_value = []

        self.ea.check_positions()

        # --- FIX: Use self.CONSTANT ---
        call_secure_tp1_1 = call({"action": self.TRADE_ACTION_SLTP, "position": 401, "sl": entry1, "tp": tp1_target, "symbol": 'GBPUSD', "comment": ANY})
        call_secure_tp1_2 = call({"action": self.TRADE_ACTION_SLTP, "position": 402, "sl": entry1, "tp": tp1_sib_target, "symbol": 'GBPUSD', "comment": ANY})
        call_secure_sec1 = call({"action": self.TRADE_ACTION_SLTP, "position": 501, "sl": entry1, "tp": tp2_target1, "symbol": 'GBPUSD', "comment": ANY})
        call_secure_sec2 = call({"action": self.TRADE_ACTION_SLTP, "position": 502, "sl": entry1, "tp": tp2_target2, "symbol": 'GBPUSD', "comment": ANY})
        self.assertEqual(self.mock_order_send.call_count, 4)
        self.mock_order_send.assert_has_calls([call_secure_tp1_1, call_secure_tp1_2, call_secure_sec1, call_secure_sec2], any_order=True)
        self.assertIn(401, self.ea.secured_positions)
        self.assertIn(402, self.ea.secured_positions)
        self.assertIn(501, self.ea.secured_positions)
        self.assertIn(502, self.ea.secured_positions)
        key_log_lines = self._read_key_log_lines()
        self.assertEqual(len(key_log_lines), 3, f"Log content: {''.join(key_log_lines)}")
        self.assertTrue(any("[TP1_SECURED]" in line and "Position 401" in line for line in key_log_lines), f"Log content: {''.join(key_log_lines)}")
        self.assertTrue(any("[SECOND_PRICE_SECURED]" in line and "Position 501" in line and f"FIRST price entry {entry1}" in line for line in key_log_lines), f"Log content: {''.join(key_log_lines)}")
        self.assertTrue(any("[SECOND_PRICE_SECURED]" in line and "Position 502" in line and f"FIRST price entry {entry1}" in line for line in key_log_lines), f"Log content: {''.join(key_log_lines)}")


    def test_06_standalone_position_ignored(self):
        """Standalone position meeting TP conditions should NOT be secured."""
        print("\nRunning Test: test_06_standalone_position_ignored")
        entry_price = 150.00
        tp_price = 151.00
        current_price = 150.99
        pos_time = int(datetime.now(timezone.utc).timestamp())

        # --- FIX: Use self.CONSTANT ---
        mock_pos_standalone = create_mock_position(ticket=601, symbol='XAUUSD', p_type=self.ORDER_TYPE_BUY,
                                            price_open=entry_price, sl=149.00, tp=tp_price,
                                            price_current=current_price, p_time=pos_time)
        self.mock_positions_get.return_value = [mock_pos_standalone]
        self.mock_orders_get.return_value = []
        self.mock_symbol_info.side_effect = lambda symbol: create_mock_symbol_info(symbol, digits=2 if symbol == 'XAUUSD' else 5)

        self.ea.check_positions()

        self.mock_order_send.assert_not_called()
        self.assertNotIn(601, self.ea.secured_positions)
        key_log_lines = self._read_key_log_lines()
        self.assertEqual(len(key_log_lines), 0, f"Log content: {''.join(key_log_lines)}")


    def test_07_already_secured_position_ignored(self):
        """Position already secured at entry should not trigger actions again."""
        print("\nRunning Test: test_07_already_secured_position_ignored")
        entry_price = 1.30000
        tp1_price = 1.30100
        current_price = 1.30099
        pos_time = int(datetime.now(timezone.utc).timestamp())

        # --- FIX: Use self.CONSTANT ---
        mock_pos_tp1 = create_mock_position(ticket=701, symbol='USDCAD', p_type=self.ORDER_TYPE_BUY,
                                            price_open=entry_price, sl=entry_price, tp=tp1_price,
                                            price_current=current_price, p_time=pos_time)
        self.mock_positions_get.return_value = [mock_pos_tp1]
        self.ea.secured_positions.add(701)

        self.ea.check_positions()

        self.mock_order_send.assert_not_called()
        self.assertIn(701, self.ea.secured_positions)
        key_log_lines = self._read_key_log_lines()
        self.assertEqual(len(key_log_lines), 0, f"Log content: {''.join(key_log_lines)}")


# --- Runner ---
if __name__ == '__main__':
    print("--- Starting PipSecureEA Logic Confirmation Tests ---")
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(TestPipSecureEALogic)
    runner = unittest.TextTestRunner(verbosity=2)
    runner.run(suite)
    print("--- Confirmation Tests Finished ---")

# --- END OF FILE confirm_ea_logic.py ---