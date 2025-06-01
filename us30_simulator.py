"""
US30 Signal Simulator - Debug Position Management System
This script simulates the exact US30 SELL signal scenario to test position grouping and TP1 logic
"""

import time
from datetime import datetime
from collections import namedtuple
import logging

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Mock MT5 constants
class MT5Constants:
    ORDER_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1
    ORDER_TYPE_BUY_LIMIT = 2
    ORDER_TYPE_SELL_LIMIT = 3

# Mock Position class (simulates MT5 position object)
Position = namedtuple('Position', [
    'ticket', 'time', 'type', 'symbol', 'volume', 'price_open', 
    'sl', 'tp', 'price_current', 'comment'
])

class MockPipSecureEA:
    """Mock version of your PipSecureEA class for testing"""
    
    def __init__(self):
        self.logger = logger
        self.secured_positions = set()
        self.time_proximity_threshold = 5  # seconds
        self.price_proximity_threshold = 10  # pips
        self.tp1_hit_groups = set()
        
    def get_pip_multiplier(self, symbol):
        """Get pip multiplier for symbol"""
        if 'US30' in symbol:
            return 1.0  # US30 uses 1 point = 1 pip
        return 0.0001
    
    def identify_position_groups(self, positions):
        """Identify position groups - your actual logic"""
        if not positions:
            return {}
            
        # Sort positions by time, then symbol, then type
        sorted_positions = sorted(positions, key=lambda p: (p.time, p.symbol, p.type))
        
        position_groups = {}
        group_counter = 0
        processed_tickets = set()
        
        for i, position in enumerate(sorted_positions):
            if position.ticket in processed_tickets:
                continue
                
            # Start a new potential group
            current_group = [position]
            processed_tickets.add(position.ticket)
            
            # Look for similar positions
            for j in range(i + 1, len(sorted_positions)):
                other_position = sorted_positions[j]
                
                if other_position.ticket in processed_tickets:
                    continue
                    
                # Check time difference
                time_diff = abs(other_position.time - position.time)
                if time_diff > self.time_proximity_threshold:
                    continue
                    
                # Check symbol and type match
                if (other_position.symbol == position.symbol and 
                    other_position.type == position.type):
                    
                    # Check price proximity
                    pip_multiplier = self.get_pip_multiplier(position.symbol)
                    if pip_multiplier > 0:
                        price_diff_in_pips = abs(other_position.price_open - position.price_open) / pip_multiplier
                        
                        # Use higher tolerance for US30
                        price_threshold = 50 if 'US30' in position.symbol else self.price_proximity_threshold
                        
                        if price_diff_in_pips <= price_threshold:
                            current_group.append(other_position)
                            processed_tickets.add(other_position.ticket)
                            self.logger.info(f"Added {other_position.ticket} to group: price diff {price_diff_in_pips:.1f} <= {price_threshold}")
                        else:
                            self.logger.info(f"Separate group for {other_position.ticket}: price diff {price_diff_in_pips:.1f} > {price_threshold}")
            
            # Store groups
            if len(current_group) >= 1:
                group_id = f"{position.symbol}_{position.type}_{group_counter}"
                position_groups[group_id] = current_group
                group_counter += 1
                
                # Log group details
                avg_price = sum(p.price_open for p in current_group) / len(current_group)
                self.logger.info(f"Group {group_id}: {len(current_group)} positions, avg entry: {avg_price:.2f}")
                for pos in current_group:
                    self.logger.info(f"  - Ticket: {pos.ticket}, Entry: {pos.price_open:.2f}, TP: {pos.tp:.2f}")
        
        return position_groups
    
    def get_position_index_in_group(self, position, group):
        """Determine TP index of position in group"""
        if not group or position.tp == 0:
            return None
            
        # Filter positions with valid TPs
        valid_tp_positions = [p for p in group if p.tp != 0]
        if not valid_tp_positions:
            return None
            
        # Sort by TP levels (for SELL: higher TP = TP1)
        is_sell = (position.type == MT5Constants.ORDER_TYPE_SELL)
        sorted_positions = sorted(valid_tp_positions, key=lambda p: p.tp, reverse=is_sell)
        
        # Find position index
        for i, pos in enumerate(sorted_positions):
            if pos.ticket == position.ticket:
                return i + 1
                
        return None
    
    def get_true_first_price_group(self, position_groups):
        """Get the group that represents the actual first price level"""
        if not position_groups:
            return None, None
            
        valid_groups = {gid: group for gid, group in position_groups.items() if len(group) > 1}
        
        if len(valid_groups) == 0:
            return None, None
            
        if len(valid_groups) == 1:
            group_id = list(valid_groups.keys())[0]
            return valid_groups[group_id], group_id
        
        # Multiple groups - for SELL: first price should be LOWER entry
        sample_position = list(valid_groups.values())[0][0]
        is_sell = sample_position.type == MT5Constants.ORDER_TYPE_SELL
        
        if is_sell:
            # For SELL: first price should be the LOWER entry (42000, not 42200)
            lowest_group = min(valid_groups.items(), key=lambda x: sum(p.price_open for p in x[1])/len(x[1]))
            avg_entry = sum(p.price_open for p in lowest_group[1]) / len(lowest_group[1])
            self.logger.info(f"SELL: First price group identified (lowest entry): {lowest_group[0]}, avg: {avg_entry:.2f}")
            return lowest_group[1], lowest_group[0]
        else:
            # For BUY: first price should be the HIGHER entry
            highest_group = max(valid_groups.items(), key=lambda x: sum(p.price_open for p in x[1])/len(x[1]))
            avg_entry = sum(p.price_open for p in highest_group[1]) / len(highest_group[1])
            self.logger.info(f"BUY: First price group identified (highest entry): {highest_group[0]}, avg: {avg_entry:.2f}")
            return highest_group[1], highest_group[0]
    
    def diagnose_tp_values(self, group):
        """Diagnose TP values in a position group"""
        self.logger.info("🔍 DIAGNOSING TP VALUES:")
        
        for i, pos in enumerate(group):
            self.logger.info(f"  Position {i+1}: Ticket={pos.ticket}, Entry={pos.price_open:.2f}, TP={pos.tp:.2f}, Current={pos.price_current:.2f}")
            
            # Calculate distance to TP for SELL positions
            if pos.tp > 0:
                if pos.type == MT5Constants.ORDER_TYPE_SELL:
                    distance_to_tp = pos.price_current - pos.tp
                    status = 'HIT' if distance_to_tp <= 0 else 'NOT HIT'
                    self.logger.info(f"    Distance to TP: {distance_to_tp:.2f} points ({status})")
                else:
                    distance_to_tp = pos.tp - pos.price_current  
                    status = 'HIT' if distance_to_tp <= 0 else 'NOT HIT'
                    self.logger.info(f"    Distance to TP: {distance_to_tp:.2f} points ({status})")
        
        # Check if all TPs are the same
        tp_values = [pos.tp for pos in group]
        unique_tps = set(tp_values)
        if len(unique_tps) == 1:
            self.logger.info(f"✅ All positions have same TP: {list(unique_tps)[0]}")
        else:
            self.logger.error(f"❌ DIFFERENT TP VALUES FOUND: {unique_tps}")
    
    def check_tp1_hit_conditions(self, position, group, current_price, position_groups):
        """Check if TP1 hit conditions are met with multi-group threshold"""
        position_index = self.get_position_index_in_group(position, group)
        if position_index != 1:
            return False, "Not TP1 position"
            
        pip_multiplier = self.get_pip_multiplier(position.symbol)
        is_sell = position.type == MT5Constants.ORDER_TYPE_SELL
        
        # Calculate pips gained
        if is_sell:
            pips_gained = (position.price_open - current_price) / pip_multiplier
        else:
            pips_gained = (current_price - position.price_open) / pip_multiplier
        
        # Calculate distance to TP
        if position.tp > 0:
            if is_sell:
                pips_to_tp = (current_price - position.tp) / pip_multiplier
            else:
                pips_to_tp = (position.tp - current_price) / pip_multiplier
                
            # Calculate progress percentage
            if is_sell:
                total_tp_pips = (position.price_open - position.tp) / pip_multiplier
            else:
                total_tp_pips = (position.tp - position.price_open) / pip_multiplier
                
            if abs(total_tp_pips) > 0.1:
                tp_progress_percent = (pips_gained / total_tp_pips) * 100
            else:
                tp_progress_percent = 100 if pips_gained >= 0 else 0
        else:
            pips_to_tp = float('inf')
            tp_progress_percent = 0
        
        self.logger.info(f"TP1 Metrics for {position.ticket}:")
        self.logger.info(f"  Pips gained: {pips_gained:.1f}")
        self.logger.info(f"  Pips to TP: {pips_to_tp:.1f}")
        self.logger.info(f"  Progress: {tp_progress_percent:.1f}%")
        
        # NEW: Fair approach for multi-group scenarios
        self.logger.info(f"  Multi-group mode: {len(position_groups) > 1}")
        
        # Check securing conditions using new fair approach
        should_secure = False
        reason = ""
        
        if len(position_groups) > 1:
            # Multi-group: Use distance-only (fair for all groups)
            if pips_to_tp <= 3:
                should_secure = True
                reason = f"within 3 pips of TP1 ({pips_to_tp:.1f} pips away) - multi-group mode"
        else:
            # Single-group: Use original system (distance + percentage)
            if pips_to_tp <= 3:
                should_secure = True
                reason = f"within 3 pips of TP1 ({pips_to_tp:.1f} pips away)"
            elif tp_progress_percent >= 80:
                should_secure = True
                reason = f"reached {tp_progress_percent:.1f}% of distance to TP1"
            
        return should_secure, reason

def create_us30_scenario():
    """Create the exact US30 SELL scenario from your problem"""
    
    logger.info("="*80)
    logger.info("CREATING US30 SELL SCENARIO")
    logger.info("="*80)
    
    # Original signal:
    # US30 SELL limit from 42000 and SELL limit from 42200
    # Tp1 @ 41800, Tp2 @ 41500, Tp3 @ 41200, Tp4 @ 40900
    # Sl @ 42400
    
    base_time = int(time.time())
    
    # Create positions for FIRST price level (42000) - activated first
    first_price_positions = [
        Position(
            ticket=100001, time=base_time, type=MT5Constants.ORDER_TYPE_SELL, 
            symbol='US30Cash', volume=0.01, price_open=42000.0, 
            sl=42400.0, tp=41800.0, price_current=41900.0, comment="Group123_TP1"
        ),
        Position(
            ticket=100002, time=base_time, type=MT5Constants.ORDER_TYPE_SELL, 
            symbol='US30Cash', volume=0.01, price_open=42000.0, 
            sl=42400.0, tp=41500.0, price_current=41900.0, comment="Group123_TP2"
        ),
        Position(
            ticket=100003, time=base_time, type=MT5Constants.ORDER_TYPE_SELL, 
            symbol='US30Cash', volume=0.01, price_open=42000.0, 
            sl=42400.0, tp=41200.0, price_current=41900.0, comment="Group123_TP3"
        ),
        Position(
            ticket=100004, time=base_time, type=MT5Constants.ORDER_TYPE_SELL, 
            symbol='US30Cash', volume=0.01, price_open=42000.0, 
            sl=42400.0, tp=40900.0, price_current=41900.0, comment="Group123_TP4"
        ),
    ]
    
    # Create positions for SECOND price level (42202.60) - activated later
    second_price_positions = [
        Position(
            ticket=100005, time=base_time + 3600, type=MT5Constants.ORDER_TYPE_SELL,  # 1 hour later
            symbol='US30Cash', volume=0.01, price_open=42202.60, 
            sl=42400.0, tp=41800.0, price_current=41900.0, comment="Group124_TP1"
        ),
        Position(
            ticket=100006, time=base_time + 3600, type=MT5Constants.ORDER_TYPE_SELL, 
            symbol='US30Cash', volume=0.01, price_open=42202.60, 
            sl=42400.0, tp=41500.0, price_current=41900.0, comment="Group124_TP2"
        ),
        Position(
            ticket=100007, time=base_time + 3600, type=MT5Constants.ORDER_TYPE_SELL, 
            symbol='US30Cash', volume=0.01, price_open=42202.60, 
            sl=42400.0, tp=41200.0, price_current=41900.0, comment="Group124_TP3"
        ),
        Position(
            ticket=100008, time=base_time + 3600, type=MT5Constants.ORDER_TYPE_SELL, 
            symbol='US30Cash', volume=0.01, price_open=42202.60, 
            sl=42400.0, tp=40900.0, price_current=41900.0, comment="Group124_TP4"
        ),
    ]
    
    return first_price_positions + second_price_positions

def simulate_price_movement_to_tp1():
    """Simulate price moving to within 3 pips of TP1 level"""
    logger.info("\n" + "="*80)
    logger.info("SIMULATING PRICE MOVEMENT TO WITHIN 3 PIPS OF TP1 (41803.0)")
    logger.info("="*80)
    
    # Update positions with current price within 3 pips of TP1 (41800)
    positions = create_us30_scenario()
    tp1_close_price = 41803.0  # 3 pips away from TP1 at 41800
    
    # Update current price for all positions
    updated_positions = []
    for pos in positions:
        updated_pos = pos._replace(price_current=tp1_close_price)
        updated_positions.append(updated_pos)
    
    return updated_positions

def run_simulation():
    """Run the complete simulation"""
    
    # Initialize mock EA
    ea = MockPipSecureEA()
    
    # Phase 1: Create initial scenario
    logger.info("PHASE 1: Initial position setup")
    positions = create_us30_scenario()
    
    # Phase 2: Identify position groups
    logger.info("\nPHASE 2: Identifying position groups")
    position_groups = ea.identify_position_groups(positions)
    
    # Phase 3: Identify true first price group
    logger.info("\nPHASE 3: Identifying true first price group")
    true_first_group, true_first_group_id = ea.get_true_first_price_group(position_groups)
    
    if true_first_group:
        logger.info(f"True first price group: {true_first_group_id}")
        ea.diagnose_tp_values(true_first_group)
    
    # Phase 4: Simulate price movement to TP1
    logger.info("\nPHASE 4: Price movement to TP1 level")
    positions_at_tp1 = simulate_price_movement_to_tp1()
    
    # Re-identify groups with updated prices
    position_groups_updated = ea.identify_position_groups(positions_at_tp1)
    true_first_group_updated, true_first_group_id = ea.get_true_first_price_group(position_groups_updated)
    
    # Phase 5: Check TP1 hit conditions for each group
    logger.info("\nPHASE 5: Checking TP1 hit conditions")
    
    # Store the true first group ID for final analysis
    _, true_first_group_id_final = ea.get_true_first_price_group(position_groups_updated)
    
    for group_id, group in position_groups_updated.items():
        logger.info(f"\nChecking group: {group_id}")
        ea.diagnose_tp_values(group)
        
        # Find TP1 position in this group
        for position in group:
            position_index = ea.get_position_index_in_group(position, group)
            if position_index == 1:  # This is TP1
                should_secure, reason = ea.check_tp1_hit_conditions(position, group, 41803.0, position_groups_updated)
                logger.info(f"TP1 Position {position.ticket}: {'SHOULD SECURE' if should_secure else 'NO ACTION'} - {reason}")
                
                if should_secure:
                    logger.info(f"🎯 GROUP {group_id} WOULD TRIGGER SECURING ACTIONS!")
                    
                    # Show what would happen
                    if group_id == true_first_group_id_final:
                        logger.info("  ✅ This is the TRUE first price group - actions would be correct")
                        logger.info(f"  📝 Would secure all positions in this group at their entry prices")
                        for pos in group:
                            logger.info(f"    - Position {pos.ticket}: secure at {pos.price_open}")
                    else:
                        logger.info("  ❌ This is NOT the first price group - BUG DETECTED!")
                        logger.info(f"  📝 Would incorrectly secure positions and trigger Rule 2")
                break
    
    # Phase 6: Show the expected vs actual behavior
    logger.info("\nPHASE 6: EXPECTED vs ACTUAL BEHAVIOR")
    logger.info("="*50)
    
    logger.info("EXPECTED behavior with Fair Approach:")
    logger.info("- Multi-group mode: Only 3-pips rule applies")
    logger.info("- Price at 41803 = 3 pips from TP1 (41800)")
    logger.info("- First price group (42000) should trigger: within 3 pips")
    logger.info("- Second price group (42202.60) should NOT trigger: still far from TP1")
    logger.info("- Fair treatment: Both groups use same 3-pips rule")
    
    logger.info("\nACTUAL behavior (from your logs):")
    logger.info("- Second price group (42202.60) triggered securing")
    logger.info("- All positions secured at 42202.60")
    logger.info("- First price TP1 never triggered")
    
    logger.info(f"\nROOT CAUSE ANALYSIS:")
    if len(position_groups_updated) > 1:
        # Check if any group would trigger with the new logic
        triggered_groups = []
        for group_id, group in position_groups_updated.items():
            for position in group:
                position_index = ea.get_position_index_in_group(position, group)
                if position_index == 1:
                    should_secure, reason = ea.check_tp1_hit_conditions(position, group, 41803.0, position_groups_updated)
                    if should_secure:
                        triggered_groups.append((group_id, reason))
                    break
        
        if triggered_groups:
            logger.info("✅ FIX WORKING: The following groups would trigger:")
            for group_id, reason in triggered_groups:
                logger.info(f"  - {group_id}: {reason}")
                if group_id == true_first_group_id_final:
                    logger.info("    ✅ CORRECT: This is the first price group!")
                else:
                    logger.info("    ❌ WRONG: This is not the first price group!")
        else:
            logger.info("❌ NO GROUPS TRIGGER: Threshold may need further adjustment")
    else:
        logger.info("✅ Single group detected - issue may be in TP assignment or hit detection")

if __name__ == "__main__":
    run_simulation()