import json
import logging
import os
import time
import fcntl
import asyncio
from pathlib import Path
from typing import Optional, List
from .models import SyncState, SyncStatus
from .config import settings

logger = logging.getLogger(__name__)

class StateManager:
    def __init__(self, path: str):
        self.path = Path(path)
        self.state = SyncState()
        self.read_only = False
        self._load()

    def _load(self):
        if not self.path.exists():
            logger.info(f"No state file found at {self.path}, creating new.")
            return

        try:
            with open(self.path, 'r') as f:
                data = json.load(f)
                self.state = SyncState(**data)
        except Exception as e:
            logger.error(f"Failed to load state: {e}. Starting fresh.", exc_info=True)

    def save(self):
        if not settings.PERSIST_ENABLED or self.read_only:
            return

        tmp_path = self.path.with_suffix('.tmp')
        try:
            # Atomic write pattern with locking
            with open(tmp_path, 'w') as f:
                # Try to acquire lock
                try:
                    fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    logger.warning("Could not acquire lock for state save. Skipping save cycle.")
                    return
                
                try:
                    json.dump(self.state.model_dump(), f, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
                finally:
                    fcntl.flock(f, fcntl.LOCK_UN)
            
            # Atomic rename
            os.rename(tmp_path, self.path)
            
        except OSError as e:
            logger.error(f"Failed to save state to {self.path}: {e}")
            # If we can't write, switch to read-only to be safe for this run
            self.read_only = True 

    def update_watchlist(self, asins: List[str]):
        """Update watchlist maintaining LRU order and max size."""
        current = set(self.state.watchlist)
        new_items = [a for a in asins if a not in current]
        
        # Remove existing if present to move to end (most recently used)
        for asin in asins:
            if asin in current:
                self.state.watchlist.remove(asin)
        
        # Append to end
        self.state.watchlist.extend(asins)
        
        # Trim from beginning
        if len(self.state.watchlist) > settings.WATCHLIST_MAX_SIZE:
            self.state.watchlist = self.state.watchlist[-settings.WATCHLIST_MAX_SIZE:]

    def get_sync_status(self, asin: str) -> SyncStatus:
        if asin not in self.state.items:
            self.state.items[asin] = SyncStatus(asin=asin)
        return self.state.items[asin]
