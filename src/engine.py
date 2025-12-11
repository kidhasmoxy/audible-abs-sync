import logging
import time
from typing import Optional, Tuple
from .config import settings
from .models import SyncItem, SyncStatus
from .state import StateManager

logger = logging.getLogger(__name__)

class SyncEngine:
    def __init__(self, state_manager: StateManager):
        self.sm = state_manager

    def update_post_sync_state(self, asin: str, pushed_audible_ms: Optional[int] = None, pushed_abs_s: Optional[float] = None):
        """
        Updates the last_seen values after a successful push to prevent ping-pong detection in the next loop.
        """
        status = self.sm.get_sync_status(asin)
        if pushed_audible_ms is not None:
            status.last_seen_audible_position_ms = pushed_audible_ms
        if pushed_abs_s is not None:
            status.last_seen_abs_position_s = pushed_abs_s

    def sync_item(self, item: SyncItem, current_audible_ms: Optional[int], current_abs_s: Optional[float]):
        """
        Determines and returns (update_audible_to_ms, update_abs_to_s).
        Returns (None, None) if no update needed.
        """
        asin = item.asin
        status = self.sm.get_sync_status(asin)
        now = time.time()

        # Inputs
        audible_pos_s = current_audible_ms / 1000.0 if current_audible_ms is not None else None
        abs_pos_s = current_abs_s

        # 1. Detect Changes
        audible_changed = False
        if audible_pos_s is not None:
            delta = abs(audible_pos_s - (status.last_seen_audible_position_ms / 1000.0))
            if delta > settings.SYNC_TOLERANCE_SECONDS:
                audible_changed = True
                logger.info(f"Change detected on Audible for {asin}: {status.last_seen_audible_position_ms/1000.0:.1f}s -> {audible_pos_s:.1f}s")
                status.last_change_detected_audible_at = now
                status.last_seen_audible_position_ms = current_audible_ms

        abs_changed = False
        if abs_pos_s is not None:
            delta = abs(abs_pos_s - status.last_seen_abs_position_s)
            if delta > settings.SYNC_TOLERANCE_SECONDS:
                abs_changed = True
                logger.info(f"Change detected on ABS for {asin}: {status.last_seen_abs_position_s:.1f}s -> {abs_pos_s:.1f}s")
                status.last_change_detected_abs_at = item.abs_updated_at or now
                status.last_seen_abs_position_s = abs_pos_s

        if not audible_changed and not abs_changed:
            return None, None

        # 2. One-Way Sync checks
        if settings.ONE_WAY_MODE == "audible_to_abs":
            if audible_changed and abs_pos_s is not None:
                return None, audible_pos_s
            return None, None
        elif settings.ONE_WAY_MODE == "abs_to_audible":
            if abs_changed and audible_pos_s is not None:
                return int(abs_pos_s * 1000), None
            return None, None

        # 3. Bidirectional Resolution
        target_audible = None
        target_abs = None

        if audible_changed and not abs_changed:
            # Audible moved, ABS didn't -> Push to ABS
            if abs_pos_s is not None: # Only push if ABS knows about this item
                target_abs = audible_pos_s
        
        elif abs_changed and not audible_changed:
            # ABS moved, Audible didn't -> Push to Audible
            if audible_pos_s is not None:
                target_audible = int(abs_pos_s * 1000)
        
        elif audible_changed and abs_changed:
            # Conflict! Both moved since last sync.
            logger.info(f"Conflict detected for {asin}. Audible: {audible_pos_s}s, ABS: {abs_pos_s}s")
            
            # Timestamp strategy
            ts_audible = status.last_change_detected_audible_at
            ts_abs = status.last_change_detected_abs_at
            
            time_diff = ts_audible - ts_abs
            
            # If explicit timestamps differ significantly, trust the newer one
            if abs(time_diff) >= settings.SYNC_CONFLICT_MIN_TIME_DELTA_SECONDS:
                if time_diff > 0: # Audible is newer
                    target_abs = audible_pos_s
                    logger.info(f"Resolving conflict for {asin}: Audible is newer by {time_diff:.1f}s")
                else: # ABS is newer
                    target_audible = int(abs_pos_s * 1000)
                    logger.info(f"Resolving conflict for {asin}: ABS is newer by {-time_diff:.1f}s")
            else:
                # Timestamps close. Check progress distance.
                # Usually we want the furthest point (forward progress), 
                # unless it's a huge jump which might be a legitimate seek/rewind.
                # Since we don't track 'max_reached', we assume further is better.
                if audible_pos_s > abs_pos_s:
                    # Audible is further ahead
                    # Check if it's not a crazy jump forward? No, usually forward is safe.
                    target_abs = audible_pos_s
                    logger.info(f"Resolving conflict for {asin}: Audible is further ahead")
                else:
                    target_audible = int(abs_pos_s * 1000)
                    logger.info(f"Resolving conflict for {asin}: ABS is further ahead")

        # 4. Cooldown & Safety Checks
        
        # Cooldown: Don't push to Audible if we just pushed recently
        if target_audible is not None:
            logger.info(f"Preparing to push {target_audible/1000.0:.1f}s to Audible for {asin}")
            if (now - status.last_pushed_to_audible_at) < settings.SYNC_COOLDOWN_SECONDS:
                # Unless change is massive (e.g. > 5 min), skip
                if abs(target_audible - status.last_seen_audible_position_ms) < 300000:
                    logger.info(f"Skipping push to Audible for {asin} due to cooldown")
                    target_audible = None
            else:
                status.last_pushed_to_audible_at = now

        # Cooldown: Don't push to ABS if we just pushed recently
        if target_abs is not None:
             logger.info(f"Preparing to push {target_abs:.1f}s to ABS for {asin}")
             if (now - status.last_pushed_to_abs_at) < settings.SYNC_COOLDOWN_SECONDS:
                 if abs(target_abs - status.last_seen_abs_position_s) < 300:
                    logger.info(f"Skipping push to ABS for {asin} due to cooldown")
                    target_abs = None
             else:
                 status.last_pushed_to_abs_at = now
        
        # Rewind protection (optional, if implementing strict safety)
        # if target_abs and target_abs < abs_pos_s - settings.SYNC_MAX_REWIND_SECONDS: ...

        return target_audible, target_abs
