from pydantic import BaseModel, Field
from typing import Dict, List, Optional, Set

class SyncItem(BaseModel):
    asin: str
    audible_pos_s: Optional[float] = None
    abs_pos_s: Optional[float] = None
    duration_s: Optional[float] = None
    abs_item_id: Optional[str] = None
    
    # Timestamps
    audible_updated_at: float = 0  # Timestamp when we detected/read the change
    abs_updated_at: float = 0      # Explicit lastUpdate from ABS or detection time

class SyncStatus(BaseModel):
    asin: str
    last_seen_audible_position_ms: int = 0
    last_seen_abs_position_s: float = 0.0
    last_change_detected_audible_at: float = 0.0
    last_change_detected_abs_at: float = 0.0
    last_pushed_to_audible_at: float = 0.0
    last_pushed_to_abs_at: float = 0.0
    last_sync_result: str = "ok"
    error_count: int = 0

class SyncState(BaseModel):
    watchlist: List[str] = Field(default_factory=list)  # Ordered by LRU (recent last)
    items: Dict[str, SyncStatus] = Field(default_factory=dict)
    last_library_discovery: float = 0.0
    last_deep_scan: float = 0.0
    last_successful_sync: float = 0.0
