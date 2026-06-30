# Junimo-Api Data Protocol

Version: **0.2**
Status: All endpoints below are implemented and covered by tests.

This document is the source of truth for the JSON contract between the
Junimo-Api backend and any frontend / consumer. The backend implements this
contract; frontends should code against this document, not against ad-hoc
field discovery.

---

## 0. General rules

- REST + JSON, UTF-8 everywhere.
- Coordinates: farm data uses **in-game tile coordinates**. Origin top-left,
  x grows right, y grows down. Grid is at most `80×65`; the actual size is
  echoed in `data.size`.
- Field discipline: unambiguous semantic fields are returned verbatim from
  the save XML; rendering-derived fields that are easy to drift between front
  and back (fence/floor/hoeDirt `orientation`) are precomputed by the backend.
- Time fields (`source_mtime`, `parsed_at`): UNIX epoch seconds, float.
- Cache contract: see §3.
- Auth: write endpoints optionally require `Authorization: Bearer <JUNIMO_API_TOKEN>`.
  Read endpoints are always open.

## 1. Endpoints

| Method | Path                       | Auth | Purpose                                             |
|--------|----------------------------|------|-----------------------------------------------------|
| GET    | `/healthz`                 | no   | Liveness probe                                      |
| GET    | `/saves`                   | no   | List slots + cache state                            |
| GET    | `/saves/{slot}`            | no   | Player / animals / friendships / stats (lightweight)|
| GET    | `/saves/{slot}/farm`       | no   | Farm tiles / buildings / crops / fences (renderer)  |
| GET    | `/saves/{slot}/full`       | no   | `summary` + `farm` combined (one round-trip for SPAs)|
| POST   | `/saves/{slot}/refresh`    | yes  | Force re-parse of one slot                          |
| POST   | `/refresh`                 | yes  | Force re-parse of every slot                        |

> `/saves/{slot}` and `/saves/{slot}/farm` share one cache entry per slot —
> they are two views over the same parse.

## 2. Schemas

### 2.1 `GET /healthz`

```json
{
  "status": "ok",
  "saves_dir": "/saves",
  "saves_dir_exists": true
}
```

### 2.2 `GET /saves`

```json
{
  "slots": [
    {
      "slot": "Junimo_123456789",
      "source_path": "/saves/Junimo_123456789/Junimo_123456789",
      "source_mtime": 1751277312.0,
      "source_size": 5427183,
      "cached": true,
      "cache_fresh": true
    }
  ]
}
```

- `cache_fresh = true` ⇔ `(mtime, size)` matches the current cache entry **and**
  the entry hasn't aged past TTL.
- Empty layout returns `{"slots": []}`.

### 2.3 `GET /saves/{slot}` — player view

Top level is the cache-entry envelope plus `data`:

```jsonc
{
  "slot": "...",
  "source_path": "...",
  "source_mtime": 1751277312.0,
  "source_size": 5427183,
  "parsed_at": 1751277400.21,
  "parse_duration_ms": 184.7,
  "data": {
    "uniqueIDForThisGame": 123456789,
    "currentSeason": "summer",                // spring|summer|fall|winter
    "isV1_3OrNewer": true,
    "petName": "Junimo",                       // or null
    "dateString": "3rd of Summer, Year 2",     // always English; i18n is the frontend's job
    "animals": {
      "White Chicken": [
        { "name": "Cluck", "age": 12, "happiness": 255,
          "homeX": 4, "homeY": 5, "building": "Big Coop" }
      ],
      "horse": "Pony"
    },
    "player": { /* see §2.5 */ },
    "farmhands": [ /* same shape as player */ ]
  }
}
```

### 2.4 `GET /saves/{slot}/farm` — render view

This is everything a canvas / SVG / WebGL frontend needs.

```jsonc
{
  "slot": "...",
  "source_mtime": 1751277312.0,
  "parsed_at": 1751277400.21,
  "data": {
    "mapType": "Default",                    // Default|Riverland|Forest|Hilltop|Wilderness|FourCorners|Beach|Island
    "mapTypeIndex": 0,
    "size": { "width": 80, "height": 65 },   // tile units

    "house":      { "x": 58, "y": 14, "width": 10, "height": 6, "upgradeLevel": 2 },
    "greenhouse": { "x": 25, "y": 12, "unlocked": true },

    "buildings": [
      {
        "name": "Building",
        "buildingType": "Big Coop",
        "x": 64, "y": 6, "width": 6, "height": 6,
        "upgradeLevel": 0,                                      // cabin only
        "fishPond": {                                           // fish pond only
          "nettingStyle": 0,
          "waterColor": [25, 155, 178],
          "hasOutput": false
        }
      }
    ],

    "objects": [
      {
        "name": "Object",
        "displayName": "Scarecrow",
        "x": 60, "y": 18,
        "index": 8,                 // parentSheetIndex
        "type": "Crafting",
        "flipped": false,
        "extra": "Scarecrow"        // typically equals displayName; for chests:
                                    // {"name":"Chest","tint":[r,g,b]}
      }
    ],

    "fences": [
      {
        "name": "Fence",
        "x": 60, "y": 19,
        "index": 0,                 // parentSheetIndex
        "type": 1,                  // whichType
        "flipped": false,
        "isGate": false,
        "orientation": 12           // backend-precomputed from NESW bitmask
      }
    ],

    "flooring": [
      { "name": "Flooring", "x": 60, "y": 20, "type": 3, "view": 0,
        "flipped": false, "orientation": 12 }
    ],

    "hoeDirt": [
      { "name": "HoeDirt", "x": 60, "y": 21, "type": 0,
        "flipped": false, "orientation": 0 }
    ],

    "crops": [
      {
        "name": "Crop",
        "x": 60, "y": 21,
        "rowInSpriteSheet": 23,
        "currentPhase": 2,
        "flipped": false,
        "dead": false,
        "tint": null
        // For flowers (rowInSpriteSheet 26/27/28/29/31):
        // "tint": { "rgb": [255, 128, 128], "daysOfCurrentPhase": 4 }
      }
    ],

    "terrainFeatures": [
      { "name": "Tree",      "x": 5, "y": 6, "treeType": 1, "growthStage": 5, "flipped": false },
      { "name": "FruitTree", "x": 9, "y": 9, "treeType": 0, "growthStage": 4, "flipped": false },
      { "name": "Grass",     "x": 7, "y": 7, "grassType": 1, "numberOfWeeds": 4, "sourceOffset": 0, "flipped": false },
      { "name": "Tea_Bush",  "x": 8, "y": 8, "size": 1, "growthStage": 3, "flipped": false }
    ],

    "largeTerrainFeatures": [
      { "name": "Bush", "x": 30, "y": 40, "flipped": false,
        "size": 2, "tileSheetOffset": 0 }
    ],

    "resourceClumps": [
      { "name": "ResourceClump", "x": 12, "y": 13,
        "width": 2, "height": 2, "parentSheetIndex": 600 }
    ]
  }
}
```

#### 2.4.1 Field conventions

- Every entry in a tile list has `name`, `x`, `y` — safe to use
  `(name, x, y)` as a React key.
- `orientation` is a sprite index derived from a 4-neighbor bitmask
  (N=1, E=2, S=4, W=8) via fixed lookup tables:
  - `Fence`: 0..10. With a gate, the gate table is used and `type` is forced
    to `1`.
  - `HoeDirt`: 0..27.
  - `Flooring`: 0..15.
- `parentSheetIndex` / `type` / `treeType` / `growthStage` / `grassType` /
  `floorType` keep their **raw numeric values** — frontends index sprite
  sheets by integer.
- "Not found" values are always `null`, not omitted, so the TS type is 1:1
  with the JSON shape.

### 2.5 player sub-structure

```jsonc
{
  "name": "Hero",
  "UniqueMultiplayerID": "123",
  "isMale": "true",
  "farmName": "Anvil",
  "favoriteThing": "...",
  "catPerson": "true",
  "deepestMineLevel": "75",
  "farmingLevel": "8",
  "miningLevel": "5",
  "combatLevel": "3",
  "foragingLevel": "4",
  "fishingLevel": "6",
  "professions": ["Rancher", "Tiller"],
  "maxHealth": "100",
  "maxStamina": "270",
  "maxItems": "36",
  "money": "12345",
  "totalMoneyEarned": "98765",
  "millisecondsPlayed": "8400000",
  "friendships": { "Abigail": 1500, "Sebastian": 250 },
  "shirt": "0", "hair": "0", "skin": "0",
  "accessory": "-1", "facialHair": "-1",
  "hairstyleColor": [255, 90, 0, 255],
  "pantsColor": [46, 85, 183, 255],
  "newEyeColor": [122, 68, 74, 255],
  "dayOfMonthForSaveGame": "3",
  "seasonForSaveGame": "1",
  "yearForSaveGame": "2",
  "stats": {
    "DaysPlayed": 59,
    "StepsTaken": 12345,
    "SpecificMonstersKilled": { "Green Slime": 12 }
  },
  "portrait_info": {
    "partner": "Abigail",            // or null
    "partner_id": "456",             // multiplayer marriage only; otherwise omitted
    "cat": true,
    "children": [
      { "gender": 0, "darkSkinned": false, "daysOld": 28, "name": "Junimo Jr." }
    ]
  }
}
```

> Most scalar fields are returned **as strings** (the raw XML text), to stay
> aligned with the upstream SDV-Summary shape. Colors, friendship points and
> `stats` are already numbers. Frontends should keep one normalize layer
> (e.g. `Number(x)`) instead of normalizing at every call site. If you'd
> rather have the backend coerce to numbers, raise it on this doc.

### 2.6 `GET /saves/{slot}/full`

```json
{
  "slot": "...",
  "source_mtime": 1751277312.0,
  "parsed_at": 1751277400.21,
  "parse_duration_ms": 184.7,
  "data": {
    "summary": { /* same shape as §2.3 .data */ },
    "farm":    { /* same shape as §2.4 .data */ }
  }
}
```

### 2.7 Write endpoints

- `POST /saves/{slot}/refresh`: always re-parses, returns the same shape as
  `GET /saves/{slot}`.
- `POST /refresh`: re-parses every slot, returns:

```json
{
  "results": [
    { "slot": "Junimo_123456789", "ok": true,
      "parsed_at": 1751277400.21, "parse_duration_ms": 184.7 },
    { "slot": "Broken_999",       "ok": false, "error": "..." }
  ]
}
```

## 3. Cache / consistency contract

Frontends only need two rules:

1. On every `GET /saves/{slot}` (or `/farm`), use the response's
   `source_mtime` + `parsed_at` as the version. If you keep a client-side
   cache, key it by `(slot, source_mtime)`.
2. When the user has just saved in-game and wants the new state immediately,
   `POST /saves/{slot}/refresh` and re-fetch. **Do not poll** `GET`: the
   `GET` is already mtime-aware, so a cache hit means the file genuinely
   hasn't changed.

If real-time push (SSE / WebSocket) is added later, the event payload will
match §2.2 entries: `{"slot": "...", "source_mtime": ..., "parsed_at": ...}`.

## 4. Errors

FastAPI standard shape:

```json
{ "detail": "Slot 'foo' not found" }
```

| HTTP | Meaning                                                                 |
|------|-------------------------------------------------------------------------|
| 404  | Slot directory missing, or no parseable file in slot                    |
| 401  | Bearer token enabled but request did not present a matching token       |
| 413  | Save file exceeds `JUNIMO_MAX_SAVE_BYTES`                               |
| 500  | Parser raised; `detail` includes the underlying exception message       |

## 5. Implementation status

| Section | Status                                                                |
|---------|-----------------------------------------------------------------------|
| §2.1    | implemented (`/healthz`)                                              |
| §2.2    | implemented (`/saves`)                                                |
| §2.3    | implemented (`/saves/{slot}`)                                         |
| §2.4    | implemented (`/saves/{slot}/farm`)                                    |
| §2.5    | implemented (inside §2.3 response)                                    |
| §2.6    | implemented (`/saves/{slot}/full`)                                    |
| §2.7    | implemented for both endpoints                                        |

## 6. Versioning

This doc uses semantic-ish versioning (`major.minor`):

- **major** bump: any incompatible field rename / removal / type change.
- **minor** bump: additive changes (new endpoint, new optional field).

When a major change is required, the previous endpoints will continue to
work for one minor cycle behind a `?protocol=` query parameter; this will be
called out here before being released.
