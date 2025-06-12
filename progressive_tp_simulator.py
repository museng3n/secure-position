"""
Progressive TP System Simulator - Test New Functionality
This simulator tests the progressive TP placement and advancement system
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
    TRADE_RETCODE_DONE = 10009

# Mock Position class
Position = namedtuple('Position', [
    'ticket', 'time', 'type', 'symbol', 'volume', 'price_open', 
    'sl', 'tp', 'price_current', 'comment'
])

# Mock Order Send Result
OrderResult = namedtuple('OrderResult', ['retcode', 'order', 'comment'])

class MockProgressivePipSecureEA:
    """Mock version of PipSecureEA with progressive TP functionality"""
    
    def __init__(self):
        self.logger = logger
        self.secured_positions = set()
        self.time_proximity_threshold = 5
        self.price_proximity_threshold = 10
        self.tp1_hit_groups = set()
        
        # Progressive TP components
        self.progressive_tp_manager = MockProgressiveTPManager(self)
        
        # Mock MT5 operations
        self.mock_positions = []
        self.mock_order_counter = 200000
        
    def get_pip_multiplier(self, symbol):
        """Get pip multiplier for symbol"""
        if 'GBP' in symbol:
            return 0.0001
        return 0.0001
    
    def get_position_tp_level(self, position):
        """Extract current TP level from position comment"""
        try:
            if hasattr(position, 'comment') and position.comment and "_TP" in position.comment:
                tp_part = position.comment.split("_TP")[-1]
                return int(tp_part[0])
            return 1
        except (ValueError, IndexError):
            return 1
    
    def get_next_tp_price(self, position, signal_data, next_level):
        """Get the next TP price for progression"""
        try:
            tp_levels = signal_data.get('tp_levels', [])
            if next_level <= len(tp_levels):
                return tp_levels[next_level - 1]
            return None
        except (IndexError, KeyError):
            return None
    
    def secure_and_progress_tp(self, position, next_tp_price, next_tp_level, group_id):
        """Mock secure and progress operation"""
        self.logger.info(f"🔄 MOCK: Securing position {position.ticket} and progressing to TP{next_tp_level} at {next_tp_price}")
        
        # Update the mock position
        old_comment = position.comment
        # Preserve the original group ID from comment
        if "_TP" in old_comment:
            comment_base = old_comment.split("_TP")[0]
            new_comment = f"{comment_base}_TP{next_tp_level}"
        else:
            new_comment = f"G{group_id}_TP{next_tp_level}"
        
        # Create updated position
        updated_position = position._replace(
            sl=position.price_open,  # Secured at entry
            tp=next_tp_price,        # New TP level
            comment=new_comment      # Updated comment
        )
        
        # Update mock positions list
        for i, pos in enumerate(self.mock_positions):
            if pos.ticket == position.ticket:
                self.mock_positions[i] = updated_position
                break
        
        self.secured_positions.add(position.ticket)
        return True
    
    def close_position(self, position):
        """Mock close position operation"""
        self.logger.info(f"🔚 MOCK: Closing position {position.ticket}")
        # Remove from mock positions
        self.mock_positions = [pos for pos in self.mock_positions if pos.ticket != position.ticket]
        return True
    
    def identify_position_groups(self, positions=None):
        """Identify position groups with progressive TP awareness"""
        if positions is None:
            positions = self.mock_positions
            
        if not positions:
            return {}
            
        # Sort positions by time, symbol, type
        sorted_positions = sorted(positions, key=lambda p: (p.time, p.symbol, p.type))
        
        position_groups = {}
        group_counter = 0
        processed_tickets = set()
        
        for i, position in enumerate(sorted_positions):
            if position.ticket in processed_tickets:
                continue
                
            current_group = [position]
            processed_tickets.add(position.ticket)
            group_id = f"{position.symbol}_{position.type}_{group_counter}"
            
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
                        price_threshold = 50 if 'GBP' in position.symbol else self.price_proximity_threshold
                        
                        if price_diff_in_pips <= price_threshold:
                            current_group.append(other_position)
                            processed_tickets.add(other_position.ticket)
            
            if len(current_group) >= 1:
                position_groups[group_id] = current_group
                group_counter += 1
                
                # Log group with TP levels
                self.logger.info(f"Group {group_id}: {len(current_group)} positions")
                for pos in current_group:
                    tp_level = self.get_position_tp_level(pos)
                    self.logger.info(f"  - Ticket: {pos.ticket}, Entry: {pos.price_open:.4f}, TP{tp_level}: {pos.tp:.4f}, Volume: {pos.volume}")
        
        return position_groups
    
    def get_position_index_in_group(self, position, group):
        """Get position TP level (enhanced for progressive system)"""
        return self.get_position_tp_level(position)
    
    def should_evaluate_tp_conditions(self, group, current_price):
        """
        Realistic entry validation for progressive TP simulation.
        Assumes positions exist because entries were properly hit in the past.
        """
        if not group:
            return False
            
        sample_position = group[0]
        entry_price = sample_position.price_open
        
        # PROGRESSIVE TP SIMULATION: 
        # Assume all positions were entered properly when signal was executed
        # Current price movement is normal market progression toward TP levels
        
        self.logger.info(f"Entry validation: Position {sample_position.ticket} exists → Entry {entry_price} was valid")
        return True  # If position exists in simulation, entry was valid
    
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
        
        # Calculate distance to TP - FIXED CALCULATION
        if position.tp > 0:
            if is_sell:
                # For SELL: current price getting closer to TP means smaller difference
                pips_to_tp = abs(current_price - position.tp) / pip_multiplier
            else:
                pips_to_tp = abs(position.tp - current_price) / pip_multiplier
                
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
        
        # Add floating point tolerance for precision issues
        pip_tolerance = 3.01  # Slightly above 3 to handle floating point precision
        
        if len(position_groups) > 1:
            # Multi-group: Use distance-only (fair for all groups)
            if pips_to_tp <= pip_tolerance:
                should_secure = True
                reason = f"within 3 pips of TP1 ({pips_to_tp:.1f} pips away) - multi-group mode"
            else:
                reason = f"too far from TP1 ({pips_to_tp:.1f} pips > 3 pips) - multi-group mode"
        else:
            # Single-group: Use original system (distance + percentage)
            if pips_to_tp <= pip_tolerance:
                should_secure = True
                reason = f"within 3 pips of TP1 ({pips_to_tp:.1f} pips away)"
            elif tp_progress_percent >= 80:
                should_secure = True
                reason = f"reached {tp_progress_percent:.1f}% of distance to TP1"
            else:
                reason = f"not close enough: {pips_to_tp:.1f} pips to TP and {tp_progress_percent:.1f}% progress"
            
        # Debug the condition with exact values
        self.logger.info(f"  Exact pips_to_tp: {pips_to_tp}")
        self.logger.info(f"  Trigger evaluation: pips_to_tp({pips_to_tp}) <= {pip_tolerance}? {pips_to_tp <= pip_tolerance}")
        self.logger.info(f"  Final decision: should_secure={should_secure}")
        
        return should_secure, reason

class MockProgressiveTPManager:
    """Mock Progressive TP Manager"""
    
    def __init__(self, pip_secure_ea):
        self.ea = pip_secure_ea
        self.logger = pip_secure_ea.logger
        self.signal_data_cache = {}
    
    def cache_signal_data(self, group_id, tp_levels):
        """Cache original TP levels"""
        self.signal_data_cache[group_id] = {
            'tp_levels': tp_levels,
            'created_at': time.time()
        }
        self.logger.info(f"📚 Cached TP data for group {group_id}: {tp_levels}")
    
    def handle_tp_hit(self, position, group, group_id):
        """Handle TP hit with progressive advancement"""
        current_level = self.ea.get_position_tp_level(position)
        self.logger.info(f"🎯 TP{current_level} hit for position {position.ticket}")
        
        # Extract the correct group ID from position comment
        comment = getattr(position, 'comment', '')
        comment_group_id = None
        if comment and comment.startswith('G') and '_TP' in comment:
            comment_group_id = comment.split('_TP')[0]
        
        # Use comment group ID for cache lookup
        cache_group_id = comment_group_id or group_id
        signal_data = self.signal_data_cache.get(cache_group_id, {})
        
        self.logger.info(f"Looking up signal data with group ID: {cache_group_id}")
        
        if current_level < 4:
            next_level = current_level + 1
            next_tp_price = self.ea.get_next_tp_price(position, signal_data, next_level)
            
            if next_tp_price:
                success = self.ea.secure_and_progress_tp(position, next_tp_price, next_level, cache_group_id)
                if success:
                    self.logger.info(f"✅ Position {position.ticket} progressed: TP{current_level} → TP{next_level}")
                    return True
            else:
                self.logger.info(f"🔚 No more TPs for {position.ticket}, closing position")
                return self.ea.close_position(position)
        else:
            self.logger.info(f"🏁 TP4 hit for {position.ticket}, closing position")
            return self.ea.close_position(position)
        
        return False
    
    def should_handle_tp_progression(self, position, group, group_id):
        """Check if position should use progressive TP"""
        comment = getattr(position, 'comment', '')
        has_progressive_comment = "_TP" in comment
        
        # Extract the group ID from position comment (G12345, G67890, etc.)
        comment_group_id = None
        if has_progressive_comment and comment:
            # Extract group ID from comment like "G12345_TP1"
            if comment.startswith('G') and '_TP' in comment:
                comment_group_id = comment.split('_TP')[0]
        
        # Check if we have cached data for the comment group ID
        has_cached_data = comment_group_id and comment_group_id in self.signal_data_cache
        
        self.logger.info(f"Progressive check for {position.ticket}:")
        self.logger.info(f"  Comment: '{comment}'")
        self.logger.info(f"  Comment group ID: '{comment_group_id}'")
        self.logger.info(f"  Has cached data: {has_cached_data}")
        self.logger.info(f"  Cached groups: {list(self.signal_data_cache.keys())}")
        
        return has_progressive_comment and has_cached_data

def create_progressive_signal_scenario():
    """Create a GBPAUD progressive TP scenario"""
    logger.info("="*80)
    logger.info("CREATING GBPAUD PROGRESSIVE TP SCENARIO")
    logger.info("Original Signal:")
    logger.info("GBPAUD SELL limit from 2.102 and SELL limit from 2.108")
    logger.info("Tp1 @ 2.097, Tp2 @ 2.091, Tp3 @ 2.085, Tp4 @ 2.079")
    logger.info("Sl @ 2.114")
    logger.info("="*80)
    
    base_time = int(time.time())
    
    # Progressive TP: Only TP1 positions initially
    # First price level (2.102) - 4 positions, all at TP1
    first_price_positions = [
        Position(
            ticket=200001, time=base_time, type=MT5Constants.ORDER_TYPE_SELL,
            symbol='GBPAUD', volume=0.04, price_open=2.102,  # TP1 gets 0.04 volume
            sl=2.114, tp=2.097, price_current=2.100, comment="G12345_TP1"
        ),
        Position(
            ticket=200002, time=base_time, type=MT5Constants.ORDER_TYPE_SELL,
            symbol='GBPAUD', volume=0.04, price_open=2.102,
            sl=2.114, tp=2.097, price_current=2.100, comment="G12345_TP1"
        ),
        Position(
            ticket=200003, time=base_time, type=MT5Constants.ORDER_TYPE_SELL,
            symbol='GBPAUD', volume=0.04, price_open=2.102,
            sl=2.114, tp=2.097, price_current=2.100, comment="G12345_TP1"
        ),
        Position(
            ticket=200004, time=base_time, type=MT5Constants.ORDER_TYPE_SELL,
            symbol='GBPAUD', volume=0.04, price_open=2.102,
            sl=2.114, tp=2.097, price_current=2.100, comment="G12345_TP1"
        ),
    ]
    
    # Second price level (2.108) - 4 positions, all at TP1
    second_price_positions = [
        Position(
            ticket=200005, time=base_time + 1800, type=MT5Constants.ORDER_TYPE_SELL,  # 30 min later
            symbol='GBPAUD', volume=0.04, price_open=2.108,
            sl=2.114, tp=2.097, price_current=2.100, comment="G67890_TP1"
        ),
        Position(
            ticket=200006, time=base_time + 1800, type=MT5Constants.ORDER_TYPE_SELL,
            symbol='GBPAUD', volume=0.04, price_open=2.108,
            sl=2.114, tp=2.097, price_current=2.100, comment="G67890_TP1"
        ),
        Position(
            ticket=200007, time=base_time + 1800, type=MT5Constants.ORDER_TYPE_SELL,
            symbol='GBPAUD', volume=0.04, price_open=2.108,
            sl=2.114, tp=2.097, price_current=2.100, comment="G67890_TP1"
        ),
        Position(
            ticket=200008, time=base_time + 1800, type=MT5Constants.ORDER_TYPE_SELL,
            symbol='GBPAUD', volume=0.04, price_open=2.108,
            sl=2.114, tp=2.097, price_current=2.100, comment="G67890_TP1"
        ),
    ]
    
    return first_price_positions + second_price_positions

def simulate_tp1_hit_and_progression():
    """Simulate TP1 hit and progression to TP2"""
    logger.info("\n" + "="*80)
    logger.info("SIMULATING TP1 HIT AND PROGRESSION")
    logger.info("Price moves to 2.0973 (within 3 pips of TP1 @ 2.0970)")
    logger.info("="*80)
    
    # Price that triggers TP1 (within 3 pips) - FIXED: Make it actually 3 pips away
    trigger_price = 2.0973  # This should be 3 pips from 2.0970
    
    # Update positions with trigger price
    positions = create_progressive_signal_scenario()
    updated_positions = []
    
    for pos in positions:
        updated_pos = pos._replace(price_current=trigger_price)
        updated_positions.append(updated_pos)
    
    return updated_positions, trigger_price

def run_progressive_tp_simulation():
    """Run the complete progressive TP simulation"""
    logger.info("🚀 STARTING PROGRESSIVE TP SIMULATION")
    
    # Initialize EA with progressive TP
    ea = MockProgressivePipSecureEA()
    
    # Phase 1: Create initial scenario
    logger.info("\n📋 PHASE 1: Progressive TP Setup")
    positions = create_progressive_signal_scenario()
    ea.mock_positions = positions
    
    # Cache TP data for both groups
    tp_levels = [2.097, 2.091, 2.085, 2.079]  # Original TP1, TP2, TP3, TP4
    ea.progressive_tp_manager.cache_signal_data("G12345", tp_levels)
    ea.progressive_tp_manager.cache_signal_data("G67890", tp_levels)
    
    # Phase 2: Identify groups
    logger.info("\n🔍 PHASE 2: Identifying Position Groups")
    position_groups = ea.identify_position_groups()
    
    # Phase 3: Simulate TP1 hit
    logger.info("\n🎯 PHASE 3: Simulating TP1 Hit")
    updated_positions, trigger_price = simulate_tp1_hit_and_progression()
    ea.mock_positions = updated_positions
    
    # Test entry validation first
    logger.info("\n🔐 PHASE 4: Entry Validation Test")
    for group_id, group in position_groups.items():
        can_evaluate = ea.should_evaluate_tp_conditions(group, trigger_price)
        logger.info(f"Group {group_id} entry validation: {can_evaluate}")
        
        if can_evaluate:
            # Test TP1 hit detection and progression
            for position in group:
                tp_level = ea.get_position_tp_level(position)
                if tp_level == 1:  # TP1 position
                    logger.info(f"\n⚡ Testing TP1 hit for position {position.ticket}")
                    
                    # Use the new TP hit conditions check
                    should_secure, reason = ea.check_tp1_hit_conditions(position, group, trigger_price, position_groups)
                    
                    if should_secure:
                        logger.info(f"🎯 TP1 trigger condition met: {reason}")
                        
                        # Test progressive TP handling
                        if ea.progressive_tp_manager.should_handle_tp_progression(position, group, group_id):
                            logger.info(f"🔄 Using progressive TP system")
                            success = ea.progressive_tp_manager.handle_tp_hit(position, group, group_id)
                            if success:
                                logger.info(f"✅ Progressive TP advancement successful!")
                            else:
                                logger.info(f"❌ Progressive TP advancement failed!")
                        else:
                            logger.info(f"📝 Using standard TP system - position would be closed")
                    else:
                        logger.info(f"⏸️ TP1 trigger condition NOT met: {reason}")
                    break  # Only test first TP1 in group
    
    # Phase 5: Show final state
    logger.info("\n📊 PHASE 5: Final Position State")
    final_groups = ea.identify_position_groups()
    
    # Phase 6: Test multiple progressions
    logger.info("\n🔄 PHASE 6: Testing Multiple TP Progressions")
    
    # First, let's check if any positions were progressed to TP2
    tp2_positions = [pos for pos in ea.mock_positions if ea.get_position_tp_level(pos) == 2]
    
    if tp2_positions:
        logger.info(f"📈 Found {len(tp2_positions)} TP2 position(s) - Testing TP2 progression")
        test_position = tp2_positions[0]
        
        # Move price to hit TP2 (2.091)
        tp2_trigger_price = 2.0913  # Within 3 pips of TP2 @ 2.091
        logger.info(f"📈 Simulating TP2 hit for position {test_position.ticket} at price {tp2_trigger_price}")
        
        # Update position with TP2 trigger price
        updated_pos = test_position._replace(price_current=tp2_trigger_price)
        for i, pos in enumerate(ea.mock_positions):
            if pos.ticket == test_position.ticket:
                ea.mock_positions[i] = updated_pos
                break
        
        # Find group for this position
        final_groups = ea.identify_position_groups()
        test_group = None
        test_group_id = None
        for group_id, group in final_groups.items():
            if any(p.ticket == test_position.ticket for p in group):
                test_group = group
                test_group_id = group_id
                break
        
        if test_group:
            # Test TP2 hit conditions
            should_secure, reason = ea.check_tp1_hit_conditions(updated_pos, test_group, tp2_trigger_price, final_groups)
            
            if should_secure:
                logger.info(f"🎯 TP2 trigger condition met: {reason}")
                # Test TP2 to TP3 progression
                success = ea.progressive_tp_manager.handle_tp_hit(updated_pos, test_group, test_group_id)
                if success:
                    logger.info(f"✅ TP2 → TP3 progression successful!")
                else:
                    logger.info(f"❌ TP2 → TP3 progression failed!")
            else:
                logger.info(f"⏸️ TP2 trigger condition NOT met: {reason}")
    else:
        logger.info("📝 No TP2 positions found - TP1 progression may not have worked")
        logger.info("💡 This suggests the TP1 → TP2 advancement needs debugging")
    
    # Phase 7: Final Analysis
    logger.info("\n📊 PHASE 7: Final Analysis")
    final_groups = ea.identify_position_groups()
    
    # Analyze what happened
    logger.info("🔍 Position State Analysis:")
    for group_id, group in final_groups.items():
        logger.info(f"\nGroup {group_id}:")
        tp_levels = {}
        for pos in group:
            tp_level = ea.get_position_tp_level(pos)
            tp_levels[f"TP{tp_level}"] = tp_levels.get(f"TP{tp_level}", 0) + 1
            logger.info(f"  - Position {pos.ticket}: TP{tp_level} at {pos.tp:.4f}, SL: {pos.sl:.4f}")
        
        logger.info(f"Group TP Distribution: {tp_levels}")
    
    # Check for evidence of progression
    progression_evidence = []
    for pos in ea.mock_positions:
        tp_level = ea.get_position_tp_level(pos)
        if tp_level > 1:
            progression_evidence.append(f"Position {pos.ticket} at TP{tp_level}")
        if pos.sl == pos.price_open:
            progression_evidence.append(f"Position {pos.ticket} secured at entry")
    
    if progression_evidence:
        logger.info(f"✅ Progressive TP Evidence Found:")
        for evidence in progression_evidence:
            logger.info(f"  - {evidence}")
    else:
        logger.info(f"❌ No progressive TP evidence - system may need debugging")
    
    # Final summary
    logger.info("\n🏁 SIMULATION SUMMARY:")
    logger.info(f"Total positions remaining: {len(ea.mock_positions)}")
    logger.info(f"Secured positions: {len(ea.secured_positions)}")
    
    # Show TP level distribution
    tp_distribution = {}
    for pos in ea.mock_positions:
        tp_level = ea.get_position_tp_level(pos)
        tp_distribution[f"TP{tp_level}"] = tp_distribution.get(f"TP{tp_level}", 0) + 1
    
    logger.info("TP Level Distribution:")
    for tp, count in tp_distribution.items():
        logger.info(f"  {tp}: {count} positions")

if __name__ == "__main__":
    run_progressive_tp_simulation()