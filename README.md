# Audible <-> Audiobookshelf Sync

A production-ready, self-hosted daemon to bidirectionally synchronize listening progress between Audible and Audiobookshelf (ABS).

## Features

- **Bidirectional Sync**: Resumes playback on either platform.
- **Conflict Resolution**: Handles simultaneous listening sessions gracefully using timestamp-based resolution.
- **Efficient**: Uses a candidate set and persisted watchlist to avoid scanning your entire Audible library.
- **Resilient**: Atomic state persistence, retries with backoff, and strict safety checks.
- **Dockerized**: Easy to deploy with Docker Compose.

## Prerequisites

1. **Audiobookshelf**: Running instance with an API token.
2. **Audible Auth**: You need a valid `audible_session.json` in your data directory.

   **Generating the session file using Docker (Recommended):**
   
   Run the following command. It will print a URL to login with your browser, and then ask for the redirect URL.
   
   ```bash
   # Ensure your data directory exists
   mkdir -p data
   
   # Run the auth flow (replace 'us' with your locale if different)
   docker compose run --rm -it --entrypoint "" audible-abs-sync python -c "import audible; auth = audible.Authenticator.from_login_external(locale='us'); auth.to_file('/data/audible_session.json'); print('Saved session to /data/audible_session.json')"
   ```


## Quick Start (Docker Compose)

1. Place your `audible_session.json` in a `data/` directory.
2. Create `docker-compose.yml`:

```yaml
version: "3.8"
services:
  sync:
    image: ghcr.io/your-repo/audible-abs-sync:latest
    build: .
    volumes:
      - ./data:/data
    environment:
      - ABS_BASE_URL=http://192.168.1.100:13378
      - ABS_TOKEN=your_abs_token
      - AUDIBLE_LOCALE=us
      - AUDIBLE_AUTH_JSON_PATH=/data/audible_session.json
      - SYNC_INTERVAL_SECONDS=120
    restart: unless-stopped
```

3. Run `docker-compose up -d`.

## Configuration

All configuration is done via Environment Variables.

| Variable | Default | Description |
|----------|---------|-------------|
| `ABS_BASE_URL` | Required | URL of your ABS server |
| `ABS_TOKEN` | Required | Bearer token for ABS |
| `AUDIBLE_LOCALE` | `us` | Audible marketplace locale |
| `SYNC_INTERVAL_SECONDS` | `120` | Main sync loop interval |
| `ONE_WAY_MODE` | `bidirectional` | Options: `bidirectional`, `audible_to_abs`, `abs_to_audible` |
| `DRY_RUN` | `false` | If true, logs actions without performing them |
| `LOG_LEVEL` | `INFO` | Logging verbosity |

## How it Works

1. **Discovery**: The daemon monitors ABS "In Progress" items and maintains a "Watchlist" of recently active Audible titles.
2. **Sync Loop**: Every interval, it fetches positions for items in the watchlist.
3. **Comparison**:
   - If one side moved significantly (>5s) and the other didn't, the position is pushed.
   - If both moved, the one with the more recent change wins (based on detection time or ABS `lastUpdate`).
4. **Safety**:
   - Updates are clamped to duration.
   - Cooldowns prevent "ping-pong" updates.
   - Persistence is atomic to prevent state corruption.

## API / Health

If `HTTP_SERVER_ENABLED=true` (default false), port 8080 exposes:
- `GET /healthz`: Health check endpoint.
- `GET /metrics`: Prometheus metrics.
- `GET /status`: JSON status summary (requires `X-Token` if configured).
