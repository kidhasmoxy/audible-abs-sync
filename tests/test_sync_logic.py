import unittest
import time
from src.models import SyncItem, SyncStatus
from src.state import StateManager
from src.engine import SyncEngine
from src.config import settings

class MockStateManager:
    def __init__(self):
        self.items = {}
    def get_sync_status(self, asin):
        if asin not in self.items:
            self.items[asin] = SyncStatus(asin=asin)
        return self.items[asin]

class TestSyncEngine(unittest.TestCase):
    def setUp(self):
        self.sm = MockStateManager()
        self.engine = SyncEngine(self.sm)
        # Reset settings
        settings.SYNC_TOLERANCE_SECONDS = 5
        settings.SYNC_CONFLICT_MIN_TIME_DELTA_SECONDS = 30
        settings.ONE_WAY_MODE = "bidirectional"

    def test_no_change(self):
        item = SyncItem(asin="test", abs_pos_s=100)
        status = self.sm.get_sync_status("test")
        status.last_seen_audible_position_ms = 100000
        status.last_seen_abs_position_s = 100
        
        aud_up, abs_up = self.engine.sync_item(item, 100000, 100)
        self.assertIsNone(aud_up)
        self.assertIsNone(abs_up)

    def test_audible_moves_forward(self):
        item = SyncItem(asin="test", abs_pos_s=100)
        status = self.sm.get_sync_status("test")
        status.last_seen_audible_position_ms = 100000 # 100s
        status.last_seen_abs_position_s = 100
        
        # Audible moves to 200s
        aud_up, abs_up = self.engine.sync_item(item, 200000, 100)
        self.assertIsNone(aud_up)
        self.assertEqual(abs_up, 200.0)

    def test_conflict_audible_newer(self):
        item = SyncItem(asin="test", abs_pos_s=150) # Moved to 150s
        status = self.sm.get_sync_status("test")
        status.last_seen_audible_position_ms = 100000 # Was 100s
        status.last_seen_abs_position_s = 100
        
        now = time.time()
        # Audible changed recently
        status.last_change_detected_audible_at = now
        # ABS changed long ago (simulation)
        status.last_change_detected_abs_at = now - 100 
        
        # Audible moves to 200s
        aud_up, abs_up = self.engine.sync_item(item, 200000, 150)
        
        # Audible timestamp is newer -> Audible wins, push 200s to ABS
        self.assertIsNone(aud_up)
        self.assertEqual(abs_up, 200.0)

if __name__ == '__main__':
    unittest.main()
