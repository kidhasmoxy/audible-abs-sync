import asyncio
import logging
import signal
import sys
import uvicorn
import time
from contextlib import asynccontextmanager

from .config import settings
from .state import StateManager
from .clients.audible_client import AudibleClient
from .clients.abs_client import ABSClient
from .engine import SyncEngine
from .models import SyncItem
from . import server

# Setup logging
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
# Silence noisy libraries
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("audible").setLevel(logging.WARNING)

logger = logging.getLogger("main")

class SyncService:
    def __init__(self):
        self.running = True
        self.state_manager = StateManager(settings.STATE_PATH)
        self.audible = AudibleClient()
        self.abs = ABSClient()
        self.engine = SyncEngine(self.state_manager)
        
        # Link state manager to server module
        server.state_manager = self.state_manager

    async def setup(self):
        await self.audible.initialize()
        await self.abs.initialize()

    async def run_discovery_tasks(self):
        """Periodic slow tasks"""
        logger.info("Discovery tasks started")
        while self.running:
            try:
                now = time.time()
                
                # 1. Deep Scan (very slow)
                if settings.AUDIBLE_DEEP_SCAN_INTERVAL_SECONDS > 0:
                    if now - self.state_manager.state.last_deep_scan > settings.AUDIBLE_DEEP_SCAN_INTERVAL_SECONDS:
                        logger.info("Starting deep scan...")
                        items = await self.audible.deep_scan_progress()
                        if items:
                            self.state_manager.update_watchlist(items)
                            logger.info(f"Deep scan added {len(items)} items to watchlist")
                        self.state_manager.state.last_deep_scan = now
                        self.state_manager.save()

                # 2. Recent Purchases (medium slow)
                if now - self.state_manager.state.last_library_discovery > settings.AUDIBLE_LIBRARY_DISCOVERY_INTERVAL_SECONDS:
                    logger.info("Checking for new purchases...")
                    # Look back 2x interval to be safe
                    items = await self.audible.get_newly_purchased(now - (settings.AUDIBLE_LIBRARY_DISCOVERY_INTERVAL_SECONDS * 2))
                    if items:
                        self.state_manager.update_watchlist(items)
                        logger.info(f"Added {len(items)} recent purchases to watchlist")
                    self.state_manager.state.last_library_discovery = now
                    self.state_manager.save()

            except Exception as e:
                logger.error(f"Error in discovery tasks: {e}", exc_info=True)

            await asyncio.sleep(60)

    async def sync_loop(self):
        while self.running:
            start_time = time.time()
            try:
                # 1. Build Candidate Set
                # Start with watchlist
                candidates = set(self.state_manager.state.watchlist)
                
                # Add ABS in-progress
                abs_items = await self.abs.get_in_progress()
                for asin in abs_items.keys():
                    candidates.add(asin)

                # Add Audible Recently Played (poll live activity)
                recent_audible = await self.audible.get_recently_played(limit=settings.AUDIBLE_RECENTLY_PLAYED_LIMIT)
                if recent_audible:
                    for asin in recent_audible:
                        candidates.add(asin)
                    # Update watchlist to persist these active items
                    self.state_manager.update_watchlist(recent_audible)

                candidate_list = list(candidates)
                if not candidate_list:
                    logger.debug("No candidates to sync.")
                else:
                    logger.info(f"Syncing {len(candidate_list)} candidates...")
                    
                    # Update Watchlist with active items to keep them fresh in LRU
                    self.state_manager.update_watchlist(list(abs_items.keys()))

                    # 2. Fetch Audible Data
                    audible_positions = await self.audible.get_last_positions(candidate_list)
                    
                    # 3. Process Each Candidate
                    for asin in candidate_list:
                        # Construct SyncItem
                        # We might have ABS data from the bulk fetch
                        item = abs_items.get(asin)
                        if not item:
                            # Try to look it up if we don't know the ID
                            abs_id = self.abs.asin_map.get(asin)
                            if not abs_id:
                                abs_id = await self.abs.lookup_abs_item(asin)
                            
                            if abs_id:
                                # Fetch actual progress if possible
                                prog = await self.abs.get_item_progress(abs_id)
                                abs_pos = 0.0
                                abs_updated = 0
                                if prog:
                                    abs_pos = prog.get("currentTime", 0.0)
                                    abs_updated = (prog.get("lastUpdate", 0) / 1000.0) if prog.get("lastUpdate") else 0
                                
                                item = SyncItem(
                                    asin=asin, 
                                    abs_item_id=abs_id, 
                                    abs_pos_s=abs_pos,
                                    abs_updated_at=abs_updated
                                )
                            else:
                                continue # Cannot sync to ABS without ID

                        audible_pos = audible_positions.get(asin)
                        
                        target_audible, target_abs = self.engine.sync_item(
                            item, audible_pos, item.abs_pos_s
                        )
                        
                        # Apply Updates
                        if target_audible is not None:
                            await self.audible.update_position(asin, target_audible)
                        
                        if target_abs is not None:
                            await self.abs.update_progress(item.abs_item_id, target_abs)

                self.state_manager.state.last_successful_sync = time.time()
                self.state_manager.save()

            except Exception as e:
                logger.error(f"Error in sync loop: {e}", exc_info=True)

            # Wait for remainder of interval
            elapsed = time.time() - start_time
            sleep_time = max(1, settings.SYNC_INTERVAL_SECONDS - elapsed)
            await asyncio.sleep(sleep_time)

    async def start(self):
        await self.setup()
        
        tasks = [
            asyncio.create_task(self.sync_loop()),
            asyncio.create_task(self.run_discovery_tasks())
        ]
        
        if settings.HTTP_SERVER_ENABLED:
            config = uvicorn.Config(server.app, host="0.0.0.0", port=settings.HTTP_SERVER_PORT, log_level="warning")
            server_task = uvicorn.Server(config).serve()
            tasks.append(asyncio.create_task(server_task))

        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            pass
        finally:
            self.state_manager.save()

def handle_sigterm(sig, frame):
    logger.info("Received SIGTERM, shutting down...")
    sys.exit(0)

if __name__ == "__main__":
    signal.signal(signal.SIGTERM, handle_sigterm)
    service = SyncService()
    try:
        asyncio.run(service.start())
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
