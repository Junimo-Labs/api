"""Farm geometry extraction.

Adapted from SDV-Summary's `sdv/farmInfo.py` (`getFarmInfo` + `checkSurrounding`).
We keep all the data the renderer needs (objects, terrain features, crops,
buildings, fences, fishponds, greenhouse, map type) but emit plain dicts so
the frontend can do its own canvas / SVG / WebGL rendering.

Coordinate system matches the in-game tile grid (x/y in tiles).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .savefile import NS, _findtext, _get_location

MAP_TYPES = [
    "Default",
    "Riverland",
    "Forest",
    "Hilltop",
    "Wilderness",
    "FourCorners",
    "Beach",
    "Island",
]

# Adjacency bitmask -> sprite index, for tilesets where the renderer picks a
# sprite based on which of N/E/S/W neighbors share the same tile type.
_ADJ_FENCE = [5, 3, 10, 6, 5, 3, 0, 6, 9, 8, 7, 7, 2, 8, 4, 4]
_ADJ_GATE = [17, 17, 17, 17, 17, 15, 17, 17, 17, 17, 12, 17, 17, 17, 17, 17]
_ADJ_HOEDIRT = [0, 24, 25, 17, 8, 16, 1, 9, 27, 19, 26, 18, 3, 11, 2, 10]
_ADJ_DEFAULT = [0, 12, 13, 9, 4, 8, 1, 5, 15, 11, 14, 10, 3, 7, 2, 6]


def _bool(text: Optional[str]) -> bool:
    return bool(text) and text.lower() == "true"


def _int_or(text: Optional[str], default: int = 0) -> int:
    if text is None:
        return default
    try:
        return int(text)
    except ValueError:
        return default


def _xy(node) -> Tuple[int, int]:
    return (
        _int_or(_findtext(node, "X")),
        _int_or(_findtext(node, "Y")),
    )


def _compute_orientation(tiles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Per-tile sprite orientation derived from same-name neighbors.

    Mirrors `farmInfo.checkSurrounding`. The frontend can either use the
    pre-computed `orientation` index, or recompute it from raw tiles + this
    same lookup table (we expose neither bitmask nor table; orientation is
    enough for vanilla rendering).
    """
    if not tiles:
        return []

    width = 80
    height = 65
    grid: List[List[Optional[Dict[str, Any]]]] = [
        [None] * width for _ in range(height)
    ]
    for tile in tiles:
        x, y = tile["x"], tile["y"]
        if 0 <= y < height and 0 <= x < width:
            grid[y][x] = tile

    name = tiles[0].get("name")
    if name == "Fence":
        primary, gate = _ADJ_FENCE, _ADJ_GATE
    elif name == "HoeDirt":
        primary, gate = _ADJ_HOEDIRT, None
    else:
        primary, gate = _ADJ_DEFAULT, None

    out: List[Dict[str, Any]] = []
    for y, row in enumerate(grid):
        for x, tile in enumerate(row):
            if tile is None:
                continue
            mask = 0
            for dx, dy, bit in ((0, -1, 1), (1, 0, 2), (0, 1, 4), (-1, 0, 8)):
                ny, nx = y + dy, x + dx
                if not (0 <= ny < height and 0 <= nx < width):
                    continue
                neighbor = grid[ny][nx]
                if neighbor is None:
                    continue
                # Floors/non-gated fences only count when type matches.
                if name == "Flooring" or (
                    name == "Fence" and not tile.get("isGate")
                ):
                    if neighbor.get("type") == tile.get("type"):
                        mask |= bit
                else:
                    mask |= bit
            new_tile = dict(tile)
            if name == "Fence" and tile.get("isGate") and gate is not None:
                new_tile["orientation"] = gate[mask]
                new_tile["type"] = 1
            else:
                new_tile["orientation"] = primary[mask]
            out.append(new_tile)
    return out


def _parse_objects(farm) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Returns (non_fence_objects, fence_tiles)."""
    objects: List[Dict[str, Any]] = []
    fences: List[Dict[str, Any]] = []
    objects_el = farm.find("objects")
    if objects_el is None:
        return objects, fences

    for item in objects_el.iter("item"):
        key = item.find("key")
        value = item.find("value")
        if key is None or value is None:
            continue
        obj = value.find("Object")
        if obj is None:
            continue
        vec = key.find("Vector2")
        x, y = _xy(vec) if vec is not None else (0, 0)
        name = _findtext(obj, "name")
        try:
            sprite_index = int(_findtext(obj, "parentSheetIndex") or 0)
        except ValueError:
            sprite_index = 0
        try:
            obj_type = _findtext(obj, "type")
        except Exception:  # noqa: BLE001
            obj_type = None
        if obj_type is None:
            continue
        flipped = _bool(_findtext(obj, "flipped"))

        is_fence = bool(name and ("Fence" in name or name == "Gate"))
        if is_fence:
            is_gate = name == "Gate"
            try:
                fence_type = int(_findtext(obj, "whichType") or 0)
            except ValueError:
                fence_type = 0
            fences.append(
                {
                    "name": "Fence",
                    "x": x,
                    "y": y,
                    "index": sprite_index,
                    "type": fence_type,
                    "flipped": flipped,
                    "isGate": is_gate,
                }
            )
            continue

        extra: Any = name
        if name == "Chest":
            color = obj.find("playerChoiceColor")
            if color is not None:
                try:
                    tint = (
                        int(_findtext(color, "R") or 0),
                        int(_findtext(color, "G") or 0),
                        int(_findtext(color, "B") or 0),
                    )
                    extra = {"name": name, "tint": list(tint)}
                except ValueError:
                    pass

        objects.append(
            {
                "name": "Object",
                "displayName": name,
                "x": x,
                "y": y,
                "index": sprite_index,
                "type": obj_type,
                "flipped": flipped,
                "extra": extra,
            }
        )
    return objects, fences


def _parse_terrain(
    farm, farm_age: int, is_last_week_of_season: bool
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    tf: List[Dict[str, Any]] = []
    crops: List[Dict[str, Any]] = []
    floors: List[Dict[str, Any]] = []
    hoedirt: List[Dict[str, Any]] = []
    terrain_el = farm.find("terrainFeatures")
    if terrain_el is None:
        return tf, floors, hoedirt, crops

    for item in terrain_el.iter("item"):
        value = item.find("value")
        feature = value.find("TerrainFeature") if value is not None else None
        key_vec = item.find("key").find("Vector2") if item.find("key") is not None else None
        if feature is None or key_vec is None:
            continue
        x, y = _xy(key_vec)
        kind = feature.get(NS + "type")
        flipped = _bool(_findtext(feature, "flipped"))
        record: Dict[str, Any] = {
            "name": kind,
            "x": x,
            "y": y,
            "flipped": flipped,
        }

        if kind in ("Tree", "FruitTree"):
            record["treeType"] = _int_or(_findtext(feature, "treeType"))
            record["growthStage"] = _int_or(_findtext(feature, "growthStage"))
            tf.append(record)
        elif kind == "Flooring":
            record["floorType"] = _int_or(_findtext(feature, "whichFloor"))
            view = feature.find("whichView")
            record["view"] = _int_or(view.text) if view is not None and view.text else 0
            record["type"] = record["floorType"]
            floors.append(record)
        elif kind == "HoeDirt":
            record["type"] = 0
            hoedirt.append(record)
            crop = feature.find("crop")
            if crop is not None:
                row = _int_or(_findtext(crop, "rowInSpriteSheet"))
                tint = None
                if row in (26, 27, 28, 29, 31):
                    tc = crop.find("tintColor")
                    if tc is not None:
                        tint = {
                            "rgb": [
                                _int_or(_findtext(tc, "R")),
                                _int_or(_findtext(tc, "G")),
                                _int_or(_findtext(tc, "B")),
                            ],
                            "daysOfCurrentPhase": _int_or(_findtext(crop, "dayOfCurrentPhase")),
                        }
                crops.append(
                    {
                        "name": "Crop",
                        "x": x,
                        "y": y,
                        "rowInSpriteSheet": row,
                        "currentPhase": _int_or(_findtext(crop, "currentPhase")),
                        "flipped": _bool(_findtext(crop, "flip")),
                        "dead": _bool(_findtext(crop, "dead")),
                        "tint": tint,
                    }
                )
        elif kind == "Grass":
            record["grassType"] = _int_or(_findtext(feature, "grassType"))
            record["numberOfWeeds"] = _int_or(_findtext(feature, "numberOfWeeds"))
            record["sourceOffset"] = _int_or(_findtext(feature, "grassSourceOffset"))
            tf.append(record)
        elif kind == "Bush":
            record["name"] = "Tea_Bush"
            record["size"] = _int_or(_findtext(feature, "size"))
            date_planted = _int_or(_findtext(feature, "datePlanted"))
            age = farm_age - date_planted
            if age < 10:
                stage = 0
            elif age < 20:
                stage = 1
            else:
                stage = 2
            if stage == 2 and is_last_week_of_season:
                stage = 3
            record["growthStage"] = stage
            tf.append(record)
        else:
            tf.append(record)

    return tf, floors, hoedirt, crops


def _parse_large_terrain(farm) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    container = farm.find("largeTerrainFeatures")
    if container is None:
        return out
    for ltf in container:
        pos = ltf.find("tilePosition")
        x, y = _xy(pos) if pos is not None else (0, 0)
        out.append(
            {
                "name": ltf.get(NS + "type"),
                "x": x,
                "y": y,
                "flipped": _bool(_findtext(ltf, "flipped")),
                "size": _int_or(_findtext(ltf, "size")),
                "tileSheetOffset": _int_or(_findtext(ltf, "tileSheetOffset")),
            }
        )
    return out


def _parse_resource_clumps(farm) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    container = farm.find("resourceClumps")
    if container is None:
        return out
    for clump in container.iter("ResourceClump"):
        tile = clump.find("tile")
        x, y = _xy(tile) if tile is not None else (0, 0)
        out.append(
            {
                "name": clump.get(NS + "type") or "ResourceClump",
                "x": x,
                "y": y,
                "width": _int_or(_findtext(clump, "width")),
                "height": _int_or(_findtext(clump, "height")),
                "parentSheetIndex": _int_or(_findtext(clump, "parentSheetIndex")),
            }
        )
    return out


def _parse_buildings(farm) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    container = farm.find("buildings")
    if container is None:
        return out
    for b in container.iter("Building"):
        building_type = _findtext(b, "buildingType") or "Unknown"
        record: Dict[str, Any] = {
            "name": "Building",
            "buildingType": building_type,
            "x": _int_or(_findtext(b, "tileX")),
            "y": _int_or(_findtext(b, "tileY")),
            "width": _int_or(_findtext(b, "tilesWide")),
            "height": _int_or(_findtext(b, "tilesHigh")),
        }
        bt_lower = building_type.lower()
        if "cabin" in bt_lower:
            indoors = b.find("indoors")
            farmhand = indoors.find("farmhand") if indoors is not None else None
            level = _int_or(_findtext(farmhand, "houseUpgradeLevel")) if farmhand is not None else 0
            record["upgradeLevel"] = min(level, 2)
        if bt_lower == "fish pond":
            netting = b.find("nettingStyle")
            override = b.find("overrideWaterColor")
            color_el = override.find("Color") if override is not None else None
            if color_el is not None:
                r = _int_or(_findtext(color_el, "R"))
                g = _int_or(_findtext(color_el, "G"))
                blue = _int_or(_findtext(color_el, "B"))
                if r == 255 and g == 255 and blue == 255:
                    tint = [25, 155, 178]
                else:
                    tint = [r, g, blue]
            else:
                tint = [25, 155, 178]
            record["fishPond"] = {
                "nettingStyle": _int_or(_findtext(netting, "int")) if netting is not None else 0,
                "waterColor": tint,
                "hasOutput": b.find("output") is not None,
            }
        out.append(record)
    return out


def _has_greenhouse(root) -> bool:
    cc = _get_location(root, "CommunityCenter")
    if cc is not None:
        areas = cc.find("areasComplete")
        if areas is not None:
            booleans = areas.findall("boolean")
            if booleans and booleans[0].text == "true":
                return True
    player = root.find("player")
    if player is None:
        return False
    mail = player.find("mailReceived")
    if mail is None:
        return False
    for letter in mail.iter("string"):
        if letter.text == "ccPantry":
            return True
    return False


def extract_farm(root) -> Optional[Dict[str, Any]]:
    """Extract the rendering-relevant farm geometry from a save root.

    Returns None if the save has no Farm location.
    """
    farm = _get_location(root, "Farm")
    if farm is None:
        return None

    player = root.find("player")
    farm_age = _int_or(_findtext(player.find("stats") if player is not None else None, "DaysPlayed"))
    day_of_season = _int_or(_findtext(player, "dayOfMonthForSaveGame"))
    is_last_week = day_of_season > 21

    objects, fences = _parse_objects(farm)
    fences = _compute_orientation(fences)

    tf, floors, hoedirt, crops = _parse_terrain(farm, farm_age, is_last_week)
    floors = _compute_orientation(floors)
    hoedirt = _compute_orientation(hoedirt)

    large_tf = _parse_large_terrain(farm)
    clumps = _parse_resource_clumps(farm)
    buildings = _parse_buildings(farm)

    house_upgrade = _int_or(_findtext(player, "houseUpgradeLevel"))
    map_type_idx = _int_or(_findtext(root, "whichFarm"))
    map_type = MAP_TYPES[map_type_idx] if 0 <= map_type_idx < len(MAP_TYPES) else "Default"

    if map_type_idx == 5:
        gh_x, gh_y = 36, 31
    elif map_type_idx == 7:
        gh_x, gh_y = 14, 16
    else:
        gh_x, gh_y = 25, 12

    has_gh = _has_greenhouse(root)

    return {
        "mapType": map_type,
        "mapTypeIndex": map_type_idx,
        "size": {"width": 80, "height": 65},
        "buildings": buildings,
        "house": {
            "x": 58,
            "y": 14,
            "width": 10,
            "height": 6,
            "upgradeLevel": house_upgrade,
        },
        "greenhouse": {
            "x": gh_x,
            "y": gh_y,
            "unlocked": has_gh,
        },
        "objects": objects,
        "fences": fences,
        "terrainFeatures": tf,
        "flooring": floors,
        "hoeDirt": hoedirt,
        "crops": crops,
        "largeTerrainFeatures": large_tf,
        "resourceClumps": clumps,
    }
