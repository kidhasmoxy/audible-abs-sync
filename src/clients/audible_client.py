import logging
import audible
import asyncio
import os
from typing import List, Dict, Optional
from ..config import settings

logger = logging.getLogger(__name__)

class AudibleClient:
    def __init__(self):
        self.client: Optional[audible.AsyncClient] = None
        self._auth_ready = False

    async def initialize(self):
        if not os.path.exists(settings.AUDIBLE_AUTH_JSON_PATH):
            logger.error(f"Audible auth file not found at {settings.AUDIBLE_AUTH_JSON_PATH}")
            return

        try:
            auth = audible.Authenticator.from_file(settings.AUDIBLE_AUTH_JSON_PATH)
            self.client = audible.AsyncClient(auth=auth)
            # Verify auth
            await self.client.get("1.0/library", params={"num_results": 1})
            self._auth_ready = True
            logger.info("Audible client initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Audible client: {e}")
            self._auth_ready = False

    async def get_last_positions(self, asins: List[str]) -> Dict[str, int]:
        """Returns dict of asin -> position_ms"""
        if not self._auth_ready or not asins:
            return {}

        results = {}
        # Batch requests
        for i in range(0, len(asins), settings.AUDIBLE_BATCH_SIZE):
            batch = asins[i : i + settings.AUDIBLE_BATCH_SIZE]
            asins_str = ",".join(batch)
            try:
                data = await self.client.get(
                    "1.0/annotations/lastpositions",
                    params={"asins": asins_str}
                )
                
                # Handle different response formats
                if "last_positions" in data:
                    for pos in data["last_positions"]:
                        results[pos["asin"]] = pos["position_ms"]
                elif "asin_last_position_heard_annots" in data:
                    for item in data["asin_last_position_heard_annots"]:
                        asin = item["asin"]
                        pos_ms = item.get("last_position_heard", {}).get("position_ms")
                        if pos_ms is not None:
                            results[asin] = pos_ms
                            
            except Exception as e:
                logger.error(f"Error fetching Audible positions for batch: {e}")
                # Don't fail completely, just skip this batch
                continue
        return results

    async def update_position(self, asin: str, position_ms: int):
        if not self._auth_ready or settings.DRY_RUN:
            if settings.DRY_RUN:
                logger.info(f"[DRY RUN] Would update Audible {asin} to {position_ms}ms")
            return

        try:
            # The PUT endpoint for lastpositions might vary by library version,
            # using the standard documented one or library helper
            # audible library doesn't strictly have a helper for this specific PUT in some versions,
            # so we use the raw request.
            payload = {
                "asin": asin,
                "acr": asin,
                "position_ms": position_ms,
                "timestamp": int(asyncio.get_event_loop().time() * 1000) # Client timestamp
            }
            # audible.AsyncClient.put expects (path, body, ...)
            await self.client.put(f"1.0/lastpositions/{asin}", payload)
            logger.info(f"Updated Audible {asin} to {position_ms}ms")
        except Exception as e:
            logger.error(f"Failed to update Audible position for {asin}: {e}")

    async def get_newly_purchased(self, after_timestamp: float) -> List[str]:
        if not self._auth_ready:
            return []
        
        try:
            data = await self.client.get(
                "1.0/library",
                params={
                    "num_results": 50,
                    "sort": "-purchase_date",
                    "response_groups": "product_attrs"
                }
            )
            return [item["asin"] for item in data.get("items", []) if "asin" in item]
        except Exception as e:
            logger.error(f"Failed to fetch newly purchased: {e}")
            return []
        
    async def get_recently_played(self, limit: int = 10) -> List[str]:
        """
        Fetch the most recently accessed items from Audible library.
        Useful for catching 'old' books that the user started listening to again.
        """
        if not self._auth_ready:
            return []
            
        try:
            # sort=-DateAccessed puts most recently interacted items first
            data = await self.client.get(
                "1.0/library",
                params={
                    "response_groups": "product_attrs", # minimal
                    "sort": "-DateAccessed",
                    "num_results": limit
                }
            )
            
            asins = []
            for item in data.get("items", []):
                asin = item.get("asin")
                if asin:
                    asins.append(asin)
            
            return asins
        except Exception as e:
            logger.error(f"Failed to fetch recently played from Audible: {e}")
            return []

    async def deep_scan_progress(self) -> List[str]:
        """Scans for in-progress items."""
        if not self._auth_ready:
            return []
        
        candidates = []
        page = 1
        try:
            while len(candidates) < settings.DEEP_SCAN_MAX_IN_PROGRESS:
                data = await self.client.get(
                    "1.0/library",
                    params={
                        "num_results": 50,
                        "page": page,
                        "response_groups": "product_attrs,media,percent_complete"
                    }
                )
                items = data.get("items", [])
                if not items:
                    break
                
                for item in items:
                    pc = item.get("percent_complete")
                    if pc is not None and 0 < pc < 100:
                        candidates.append(item["asin"])
                
                page += 1
                # Circuit breaker for library size
                if page > 20: 
                    break
        except Exception as e:
            logger.error(f"Deep scan failed: {e}")
        
        return candidates
