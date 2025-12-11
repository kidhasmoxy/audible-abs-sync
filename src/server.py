from fastapi import FastAPI, Depends, HTTPException, Header
from typing import Optional
from .state import StateManager
from .config import settings

app = FastAPI(title="Audible-ABS Sync")
state_manager: Optional[StateManager] = None

def get_token(x_token: Optional[str] = Header(None, alias="X-Token")):
    if settings.HTTP_SERVER_TOKEN and x_token != settings.HTTP_SERVER_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid token")

@app.get("/healthz")
def healthz():
    if not state_manager:
        return {"status": "starting"}
    
    last_sync = state_manager.state.last_successful_sync
    # Use a lenient threshold for health check (e.g. 3 missed intervals)
    import time
    if time.time() - last_sync > (settings.SYNC_INTERVAL_SECONDS * 3 + 60):
        # We don't fail the container immediately, just report unhealthy
        # raise HTTPException(status_code=503, detail="Sync lagging")
        return {"status": "lagging", "last_sync_age": time.time() - last_sync}
    
    return {"status": "ok"}

@app.get("/status", dependencies=[Depends(get_token)])
def status():
    if not state_manager:
        return {"status": "not_ready"}
    
    return {
        "watchlist_size": len(state_manager.state.watchlist),
        "total_tracked_items": len(state_manager.state.items),
        "last_sync": state_manager.state.last_successful_sync,
        "config": {
            "interval": settings.SYNC_INTERVAL_SECONDS,
            "mode": settings.ONE_WAY_MODE
        }
    }

@app.get("/metrics")
def metrics():
    # Simple prometheus-style text format
    if not state_manager:
        return ""
    
    s = state_manager.state
    lines = [
        f'audible_abs_watchlist_size {len(s.watchlist)}',
        f'audible_abs_last_sync_timestamp {s.last_successful_sync}',
        f'audible_abs_items_tracked {len(s.items)}'
    ]
    return "\n".join(lines)
