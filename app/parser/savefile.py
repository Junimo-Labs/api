"""Stardew save XML -> dict parser.

Distilled from SDV-Summary's `sdv/savefile.py` + `sdv/playerinfo2.py`. We keep
only the data extraction (player, farmhands, animals, friendships, stats) and
return plain JSON-ready dicts.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from defusedxml import ElementTree as ET

from .validate import GIFTABLE_NPCS, MARRIAGE_CANDIDATES, SEASONS

NS = "{http://www.w3.org/2001/XMLSchema-instance}"

ANIMAL_HABITABLE_BUILDINGS = ["Coop", "Barn", "SlimeHutch"]

PROFESSIONS = [
    "Rancher", "Tiller", "Coopmaster", "Shepherd", "Artisan", "Agriculturist",
    "Fisher", "Trapper", "Angler", "Pirate", "Mariner", "Luremaster",
    "Forester", "Gatherer", "Lumberjack", "Tapper", "Botanist", "Tracker",
    "Miner", "Geologist", "Blacksmith", "Prospector", "Excavator", "Gemologist",
    "Fighter", "Scout", "Brute", "Defender", "Acrobat", "Desperado",
]

PLAYER_TAGS = [
    "name", "UniqueMultiplayerID", "isMale", "farmName", "favoriteThing",
    "catPerson", "deepestMineLevel", "farmingLevel", "miningLevel",
    "combatLevel", "foragingLevel", "fishingLevel", "professions", "maxHealth",
    "maxStamina", "maxItems", "money", "totalMoneyEarned", "millisecondsPlayed",
    "friendships", "shirt", "hair", "skin", "accessory", "facialHair",
    "hairstyleColor", "pantsColor", "newEyeColor", "dayOfMonthForSaveGame",
    "seasonForSaveGame", "yearForSaveGame",
]

PET_TYPES = ["Cat", "Dog"]
PET_LOCATIONS = ["Farm", "FarmHouse"]
CHILD_TYPES = ["Child"]
CHILD_LOCATIONS = ["Farm", "FarmHouse"]


def _str_to_bool(x: Optional[str]) -> bool:
    return bool(x) and x.lower() == "true"


def _findtext(node, tag: str) -> Optional[str]:
    if node is None:
        return None
    el = node.find(tag)
    if el is None:
        return None
    return el.text


def _get_location(root, name: str):
    locations_el = root.find("locations")
    if locations_el is None:
        return None
    for loc in locations_el.findall("GameLocation"):
        if loc.attrib.get(NS + "type") == name:
            return loc
    return None


def _iter_npcs(root, allowed_locations: List[str], allowed_types: List[str]) -> List:
    out = []
    locations_el = root.find("locations")
    if locations_el is None:
        return out
    for location in locations_el.iter("GameLocation"):
        if location.get(NS + "type") in allowed_locations:
            chars = location.find("characters")
            if chars is None:
                continue
            for npc in chars.iter("NPC"):
                if npc.get(NS + "type") in allowed_types:
                    out.append(npc)
    return out


def _get_animals(farm, npc_lookup) -> Dict[str, Any]:
    animals: Dict[str, Any] = {}
    if farm is None:
        return animals
    buildings_el = farm.find("buildings")
    if buildings_el is None:
        return animals
    for building in buildings_el.iter("Building"):
        building_type = building.get(NS + "type")
        building_name_el = building.find("buildingType")
        building_name = building_name_el.text if building_name_el is not None else None
        if building_type not in ANIMAL_HABITABLE_BUILDINGS:
            continue
        indoors = building.find("indoors")
        if indoors is None:
            continue
        animals_el = indoors.find("animals")
        if animals_el is None:
            continue
        for item in animals_el.iter("item"):
            value = item.find("value")
            farm_animal = value.find("FarmAnimal") if value is not None else None
            if farm_animal is None:
                continue
            home = farm_animal.find("homeLocation")
            entry = {
                "name": _findtext(farm_animal, "name"),
                "age": int(_findtext(farm_animal, "age") or 0),
                "happiness": int(_findtext(farm_animal, "happiness") or 0),
                "homeX": int(_findtext(home, "X") or 0) if home is not None else None,
                "homeY": int(_findtext(home, "Y") or 0) if home is not None else None,
                "building": building_name,
            }
            animal_type = _findtext(farm_animal, "type") or "Unknown"
            animals.setdefault(animal_type, []).append(entry)
    horses = npc_lookup(["Farm"], ["Horse"])
    if horses:
        animals["horse"] = _findtext(horses[0], "name")
    return animals


def _get_professions(player_node) -> List[str]:
    profs_el = player_node.find("professions")
    if profs_el is None:
        return []
    out = []
    for entry in profs_el.iter("int"):
        try:
            idx = int(entry.text)
        except (TypeError, ValueError):
            continue
        if 0 <= idx < len(PROFESSIONS) and len(out) < 10:
            out.append(PROFESSIONS[idx])
    return out


def _get_friendships(player_node, v1_3: bool) -> Dict[str, int]:
    out: Dict[str, int] = {}
    container = player_node.find("friendshipData" if v1_3 else "friendships")
    if container is None:
        return out
    for item in container:
        key_el = item.find("key")
        if key_el is None:
            continue
        name_el = key_el.find("string")
        if name_el is None or name_el.text not in GIFTABLE_NPCS:
            continue
        value_el = item.find("value")
        if value_el is None:
            continue
        if v1_3:
            points_el = value_el.find("Friendship")
            rating = int(_findtext(points_el, "Points") or 0)
        else:
            rating = int(_findtext(value_el.find("ArrayOfInt"), "int") or 0)
        out[name_el.text] = rating
    return out


def _get_partner(player_node) -> Optional[str]:
    spouse = _findtext(player_node, "spouse")
    if spouse and spouse in MARRIAGE_CANDIDATES:
        return spouse
    return None


def _get_multiplayer_partner(player_id: str, friendships_node) -> Optional[str]:
    if friendships_node is None or player_id is None:
        return None
    for item in friendships_node.iter("item"):
        try:
            farmer1 = next(item.iter("Farmer1")).text
            farmer2 = next(item.iter("Farmer2")).text
            status = next(item.iter("Status")).text
        except StopIteration:
            continue
        if status == "Married" and player_id in (farmer1, farmer2):
            return farmer1 if player_id != farmer1 else farmer2
    return None


def _get_stats(player_outer_node) -> Dict[str, Any]:
    stats: Dict[str, Any] = {}
    stats_el = player_outer_node.find("stats")
    if stats_el is None:
        return stats
    for stat in stats_el:
        tag = stat.tag[0].upper() + stat.tag[1:]
        if tag in stats:
            continue
        if stat.text is not None:
            try:
                stats[tag] = int(stat.text)
            except ValueError:
                stats[tag] = stat.text
        elif tag == "SpecificMonstersKilled":
            monsters: Dict[str, int] = {}
            for monster in stat.iter("item"):
                key_el = monster.find("key")
                value_el = monster.find("value")
                if key_el is None or value_el is None:
                    continue
                monster_name_el = key_el.find("string")
                count_el = value_el.find("int")
                if monster_name_el is None or count_el is None:
                    continue
                try:
                    monsters[monster_name_el.text] = int(count_el.text)
                except (TypeError, ValueError):
                    continue
            stats[tag] = monsters
    return stats


def _player_has_v1_3(root) -> bool:
    flag = _findtext(root, "hasApplied1_3_UpdateChanges")
    return _str_to_bool(flag)


def _player_info(node, children: List, v1_3: bool, farmer_friendships) -> Dict[str, Any]:
    player_node = node if v1_3 else node.find("player")
    if player_node is None:
        return {}

    tags = list(PLAYER_TAGS)
    if v1_3:
        tags[tags.index("friendships")] = "friendshipData"

    structural_tags = {
        "professions",
        "friendships",
        "friendshipData",
        "hairstyleColor",
        "pantsColor",
        "newEyeColor",
    }

    info: Dict[str, Any] = {}
    for tag in tags:
        el = player_node.find(tag)
        if el is None:
            continue
        if tag not in structural_tags:
            if el.text is not None:
                info[tag] = el.text
            continue
        if tag == "professions":
            info["professions"] = _get_professions(player_node)
        elif tag in ("friendships", "friendshipData"):
            info["friendships"] = _get_friendships(player_node, v1_3)
        elif tag in ("hairstyleColor", "pantsColor", "newEyeColor"):
            try:
                info[tag] = [int(el.find(c).text) for c in "RGBA"]
            except (AttributeError, TypeError, ValueError):
                continue

    info["stats"] = _get_stats(node)

    portrait: Dict[str, Any] = {}
    portrait["partner"] = _get_partner(player_node)
    if not portrait["partner"] and info.get("UniqueMultiplayerID"):
        portrait["partner_id"] = _get_multiplayer_partner(
            info["UniqueMultiplayerID"], farmer_friendships
        )
    portrait["cat"] = _str_to_bool(info.get("catPerson"))
    portrait["children"] = []
    for child in children:
        try:
            portrait["children"].append(
                {
                    "gender": int(_findtext(child, "gender") or 0),
                    "darkSkinned": _str_to_bool(_findtext(child, "darkSkinned")),
                    "daysOld": int(_findtext(child, "daysOld") or 0),
                    "name": _findtext(child, "name"),
                }
            )
        except (TypeError, ValueError):
            continue
    info["portrait_info"] = portrait
    return info


def parse_save_xml(xml_bytes: bytes) -> Dict[str, Any]:
    """Parse a Stardew Valley save XML buffer and return a JSON-ready dict.

    The shape is intentionally close to the upstream SDV-Summary fields, with
    sprite-rendering bits dropped: this service reports semantic state, not
    pixels.
    """

    root = ET.fromstring(xml_bytes)
    v1_3 = _player_has_v1_3(root)

    children = _iter_npcs(root, CHILD_LOCATIONS, CHILD_TYPES)
    farmer_friendships = root.find("farmerFriendships")

    if v1_3:
        main_player_node = root.find("player")
    else:
        main_player_node = root

    main_info = _player_info(main_player_node, children, v1_3, farmer_friendships)

    farmhands: List[Dict[str, Any]] = []
    if v1_3:
        for fh in root.iter("farmhand"):
            name = _findtext(fh, "name")
            if not name:
                continue
            farmhands.append(_player_info(fh, children, v1_3, farmer_friendships))

    pets = _iter_npcs(root, PET_LOCATIONS, PET_TYPES)
    pet_name = _findtext(pets[0], "name") if pets else None

    farm_location = _get_location(root, "Farm")
    animals = _get_animals(farm_location, lambda loc, t: _iter_npcs(root, loc, t))

    current_season = _findtext(root, "currentSeason")
    if current_season is not None and current_season not in SEASONS:
        current_season = current_season

    unique_game_id_text = _findtext(root, "uniqueIDForThisGame")
    try:
        unique_game_id = int(unique_game_id_text) if unique_game_id_text is not None else None
    except ValueError:
        unique_game_id = None

    # Backfill partner names where we only had IDs.
    all_players = [main_info] + farmhands
    by_id = {
        p.get("UniqueMultiplayerID"): p
        for p in all_players
        if p.get("UniqueMultiplayerID")
    }
    for player in all_players:
        portrait = player.get("portrait_info") or {}
        partner_id = portrait.get("partner_id")
        if partner_id and partner_id in by_id:
            portrait["partner"] = by_id[partner_id].get("name")

    return {
        "uniqueIDForThisGame": unique_game_id,
        "currentSeason": current_season,
        "isV1_3OrNewer": v1_3,
        "petName": pet_name,
        "animals": animals,
        "player": main_info,
        "farmhands": farmhands,
    }


def parse_save_file(path: Path, max_bytes: int) -> Dict[str, Any]:
    size = path.stat().st_size
    if size > max_bytes:
        raise ValueError(
            f"Save file too large: {size} bytes > limit {max_bytes} bytes"
        )
    with path.open("rb") as fh:
        data = fh.read()
    return parse_save_xml(data)
