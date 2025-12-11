import logging
import httpx
from typing import Dict, List, Optional, Tuple
from ..config import settings
from ..models import SyncItem

logger = logging.getLogger(__name__)

class ABSClient:
    def __init__(self):
        self.client = httpx.AsyncClient(
            base_url=settings.ABS_BASE_URL.rstrip('/'),
            headers={"Authorization": f"Bearer {settings.ABS_TOKEN}"},
            timeout=settings.REQUEST_TIMEOUT_SECONDS
        )
        self.user_id: Optional[str] = settings.ABS_USER_ID
        self.asin_map: Dict[str, str] = {}  # asin -> item_id
        self.libraries: List[str] = []

    async def initialize(self):
        try:
            if not self.user_id:
                resp = await self.client.get("/api/me")
                resp.raise_for_status()
                data = resp.json()
                self.user_id = data.get("user", {}).get("id") or data.get("id")
                if not self.user_id:
                    raise ValueError("Could not determine User ID")
                logger.info(f"Connected to ABS as user {self.user_id}")
            else:
                # Validate connection
                resp = await self.client.get(f"/api/users/{self.user_id}")
                resp.raise_for_status()
        except Exception as e:
            logger.error(f"Failed to initialize ABS client: {e}")
            raise

    async def get_in_progress(self) -> Dict[str, SyncItem]:
        """
        Returns map of ASIN -> SyncItem (with abs_pos filled).
        Also updates the ASIN map.
        """
        results = {}
        try:
            # Use /api/me which should be accessible and contain user data
            resp = await self.client.get("/api/me")
            resp.raise_for_status()
            data = resp.json()
            # Usually wrapped in 'user' object or at root depending on version
            user_data = data.get("user", data)
            items = user_data.get("mediaProgress", [])
            
            for prog in items:
                # Progress object usually contains 'media' expanded
                media = prog.get("media", {})
                metadata = media.get("metadata", {})
                asin = metadata.get("asin")
                
                if not asin:
                    continue

                item_id = media.get("id")
                self.asin_map[asin] = item_id
                
                current_time = prog.get("currentTime")
                duration = prog.get("duration") # or media.duration
                last_update = prog.get("lastUpdate") # ms timestamp

                if current_time is not None:
                    results[asin] = SyncItem(
                        asin=asin,
                        abs_pos_s=current_time,
                        duration_s=duration or media.get("duration"),
                        abs_item_id=item_id,
                        abs_updated_at=last_update / 1000.0 if last_update else 0
                    )
        except Exception as e:
            logger.error(f"Failed to fetch ABS in-progress: {e}")
        
        return results

    async def update_progress(self, item_id: str, position_s: float):
        if settings.DRY_RUN:
            logger.info(f"[DRY RUN] Would update ABS item {item_id} to {position_s}s")
            return

        try:
            # /api/me/progress/{itemId}
            # Payload: { currentTime: float, isFinished: bool, hideFromContinueListening: bool }
            payload = {
                "currentTime": position_s,
                "isFinished": False # Logic to detect finish handled by caller if needed
            }
            resp = await self.client.patch(f"/api/me/progress/{item_id}", json=payload)
            resp.raise_for_status()
            logger.info(f"Updated ABS item {item_id} to {position_s}s")
        except Exception as e:
            logger.error(f"Failed to update ABS progress for {item_id}: {e}")

    async def get_item_progress(self, item_id: str) -> Optional[Dict]:
        """
        Fetch progress for a specific item.
        Returns dict with currentTime, duration, lastUpdate, etc.
        """
        try:
            resp = await self.client.get(f"/api/me/progress/{item_id}")
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"Failed to fetch progress for {item_id}: {e}")
            return None

    async def refresh_asin_map(self):
        # Implementation to scan library for ASINs if needed
        # Since this can be heavy, we rely mostly on in-progress, 
        # but could do a paged library scan here similar to deep_scan.
        pass

    async def get_libraries(self) -> List[str]:
        if self.libraries:
            return self.libraries
        try:
            resp = await self.client.get("/api/libraries")
            resp.raise_for_status()
            data = resp.json()
            all_libs = [lib["id"] for lib in data.get("libraries", [])]
            
            if settings.ABS_LIBRARY_ID:
                if settings.ABS_LIBRARY_ID in all_libs:
                    self.libraries = [settings.ABS_LIBRARY_ID]
                    logger.info(f"Scoped to ABS Library ID: {settings.ABS_LIBRARY_ID}")
                else:
                    logger.warning(f"Configured ABS_LIBRARY_ID {settings.ABS_LIBRARY_ID} not found in available libraries: {all_libs}")
                    self.libraries = []
            else:
                self.libraries = all_libs
                
        except Exception as e:
            logger.error(f"Failed to fetch libraries: {e}")
        return self.libraries

    async def lookup_abs_item(self, asin: str) -> Optional[str]:
        """
        Look up ABS Item ID by ASIN using library search. Caches result.
        """
        if asin in self.asin_map:
            return self.asin_map[asin]
            
        libraries = await self.get_libraries()
        
        for lib_id in libraries:
            try:
                # Library search
                resp = await self.client.get(f"/api/libraries/{lib_id}/search", params={"q": asin})
                resp.raise_for_status()
                data = resp.json()
                
                # Results usually in 'book', 'audiobooks' or 'results'
                candidates = []
                if isinstance(data, list):
                    candidates = data
                else:
                    candidates.extend(data.get("book", []))
                    candidates.extend(data.get("audiobooks", []))
                    candidates.extend(data.get("results", []))
                
                for item in candidates:
                    # Search results might wrap item in 'libraryItem'
                    real_item = item.get("libraryItem", item)
                    
                    # Check metadata
                    media = real_item.get("media", {})
                    metadata = media.get("metadata", {})
                    
                    # Loose check on ASIN
                    if metadata.get("asin") == asin:
                        item_id = real_item.get("id")
                        if item_id:
                            self.asin_map[asin] = item_id
                            logger.debug(f"Resolved ASIN {asin} to ABS Item {item_id}")
                            return item_id
                            
            except Exception as e:
                logger.debug(f"Failed to search lib {lib_id} for {asin}: {e}")
            
        return None
