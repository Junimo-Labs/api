# Junimo-Api

A small containerized service that **parses Stardew Valley save files** and exposes a JSON API for retrieving / refreshing the parsed result. Save-parsing logic is distilled from [Sketchy502/SDV-Summary](https://github.com/Sketchy502/SDV-Summary) (the engine behind [upload.farm](http://upload.farm)) — only the pure-Python XML extraction layer is reused; Flask, Postgres, Pillow rendering and image generation are not.

## What it does

1. **Parses** every save under `JUNIMO_SAVES_DIR` (default `/saves`). Each direct subdirectory is treated as one save slot, e.g. `Junimo_123456789/Junimo_123456789`.
2. **Exposes an HTTP API** to list slots, fetch the latest parsed view of a slot, and force-refresh single slots or all slots.
3. **Caches** parsed results in memory. Cache is keyed by slot and invalidated on file `mtime` / size change. A configurable TTL (`JUNIMO_CACHE_TTL_SECONDS`, default 5min) is the upper bound — a fresh save always wins over a stale cache because the mtime check happens on every read.

## Quick start

### Docker Compose (recommended)

```bash
# Mount your real Saves directory into ./saves (read-only is fine).
# Linux:   ln -s ~/.config/StardewValley/Saves ./saves
# Windows: bind %APPDATA%/StardewValley/Saves to ./saves in compose
docker compose up --build -d

curl http://localhost:8000/healthz
curl http://localhost:8000/saves
curl http://localhost:8000/saves/Junimo_123456789 | jq .data.player.name
curl -X POST http://localhost:8000/saves/Junimo_123456789/refresh
curl -X POST http://localhost:8000/refresh
```

### Without Docker

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
JUNIMO_SAVES_DIR=/path/to/Saves uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## API

| Method | Path                          | Auth (if `JUNIMO_API_TOKEN` set) | Description |
|--------|-------------------------------|----------------------------------|-------------|
| GET    | `/healthz`                    | no                               | Liveness + saves dir check. |
| GET    | `/saves`                      | no                               | List slots with mtime / cache state. |
| GET    | `/saves/{slot}`               | no                               | Cached parsed save (re-parsed if mtime changed). |
| POST   | `/saves/{slot}/refresh`       | yes                              | Force re-parse of one slot. |
| POST   | `/refresh`                    | yes                              | Force re-parse of every slot. |

Auth is bearer-token based and only enforced when `JUNIMO_API_TOKEN` is set:
```
Authorization: Bearer <token>
```

### Sample `GET /saves/{slot}` response (truncated)

```json
{
  "slot": "Junimo_123456789",
  "source_path": "/saves/Junimo_123456789/Junimo_123456789",
  "source_mtime": 1751277312.0,
  "source_size": 5427183,
  "parsed_at": 1751277400.21,
  "parse_duration_ms": 184.7,
  "data": {
    "uniqueIDForThisGame": 123456789,
    "currentSeason": "summer",
    "isV1_3OrNewer": true,
    "petName": "Junimo",
    "dateString": "3rd of Summer, Year 2",
    "animals": { "White Chicken": [{ "name": "Cluck", "happiness": 255, ... }] },
    "player": {
      "name": "Hero", "farmName": "Anvil", "money": "12345",
      "professions": ["Rancher", "Tiller"],
      "friendships": { "Abigail": 1500, ... },
      "stats": { "DaysPlayed": 59, "StepsTaken": 12345, ... },
      "portrait_info": { "partner": null, "cat": true, "children": [] }
    },
    "farmhands": []
  }
}
```

## Configuration

All env vars use prefix `JUNIMO_`. A `.env` file in the working directory is also picked up.

| Variable                   | Default              | Notes                                                                 |
|----------------------------|----------------------|-----------------------------------------------------------------------|
| `JUNIMO_SAVES_DIR`         | `/saves`             | Root containing one directory per save slot.                          |
| `JUNIMO_CACHE_TTL_SECONDS` | `300`                | Soft upper bound; mtime always wins.                                  |
| `JUNIMO_MAX_SAVE_BYTES`    | `67108864` (64 MiB)  | Refuse to parse files larger than this.                               |
| `JUNIMO_API_TOKEN`         | unset                | When set, mutating endpoints require `Authorization: Bearer <token>`. |

## Caching semantics

- Read (`GET /saves/{slot}`):
  - If cached entry's `(mtime, size)` matches the current file and is younger than the TTL → cache hit.
  - Otherwise → re-parse under a per-slot async lock (no thundering herd).
- Refresh (`POST .../refresh`): always re-parses, regardless of TTL or mtime. Use this when you've modified a save in-place and don't want to wait for the next read.
- Eviction: slots whose directory has disappeared are dropped during `POST /refresh`.

## Save file layout assumed

```
$JUNIMO_SAVES_DIR/
├── Junimo_123456789/
│   ├── Junimo_123456789      ← XML save (this is what we parse)
│   ├── SaveGameInfo
│   └── ...
└── Hero_987654321/
    └── Hero_987654321
```

We pick `<slot>/<slot>` first. If absent, we fall back to the largest non-`SaveGameInfo` regular file in that directory.

## Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt pytest httpx
pytest -q
```

## License & attribution

Save-parsing logic adapted from [Sketchy502/SDV-Summary](https://github.com/Sketchy502/SDV-Summary). Stardew Valley © ConcernedApe.
