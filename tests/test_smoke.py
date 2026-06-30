"""Smoke tests for parser, store, and API.

Uses minimal handcrafted save XML; real saves are large and proprietary.
The XML covers enough of the schema to exercise both summary and farm
parsers, the cache, and the documented protocol envelopes.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.parser.savefile import parse_save_xml
from app.store import SaveStore


MINIMAL_SAVE_XML = b"""<?xml version="1.0" encoding="utf-8"?>
<SaveGame xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <player>
    <name>Test</name>
    <UniqueMultiplayerID>1</UniqueMultiplayerID>
    <farmName>Anvil</farmName>
    <isMale>true</isMale>
    <catPerson>true</catPerson>
    <money>1000</money>
    <farmingLevel>5</farmingLevel>
    <dayOfMonthForSaveGame>3</dayOfMonthForSaveGame>
    <seasonForSaveGame>1</seasonForSaveGame>
    <yearForSaveGame>2</yearForSaveGame>
    <houseUpgradeLevel>1</houseUpgradeLevel>
    <stats>
      <DaysPlayed>59</DaysPlayed>
    </stats>
    <professions>
      <int>0</int>
      <int>1</int>
    </professions>
    <friendshipData />
    <mailReceived>
      <string>ccPantry</string>
    </mailReceived>
  </player>
  <farmerFriendships />
  <locations>
    <GameLocation xsi:type="Farm">
      <buildings>
        <Building xsi:type="Coop">
          <buildingType>Coop</buildingType>
          <tileX>64</tileX><tileY>6</tileY>
          <tilesWide>6</tilesWide><tilesHigh>3</tilesHigh>
          <indoors xsi:type="AnimalHouse">
            <animals>
              <item>
                <key><int>1</int></key>
                <value><FarmAnimal>
                  <name>Cluck</name>
                  <age>10</age>
                  <type>White Chicken</type>
                  <happiness>200</happiness>
                  <homeLocation><X>1</X><Y>2</Y></homeLocation>
                </FarmAnimal></value>
              </item>
            </animals>
          </indoors>
        </Building>
      </buildings>
      <terrainFeatures>
        <item>
          <key><Vector2><X>10</X><Y>10</Y></Vector2></key>
          <value><TerrainFeature xsi:type="Tree">
            <treeType>1</treeType>
            <growthStage>5</growthStage>
            <flipped>false</flipped>
          </TerrainFeature></value>
        </item>
        <item>
          <key><Vector2><X>11</X><Y>10</Y></Vector2></key>
          <value><TerrainFeature xsi:type="HoeDirt">
            <flipped>false</flipped>
            <crop>
              <currentPhase>2</currentPhase>
              <rowInSpriteSheet>23</rowInSpriteSheet>
              <flip>false</flip>
              <dead>false</dead>
              <dayOfCurrentPhase>1</dayOfCurrentPhase>
              <tintColor><R>0</R><G>0</G><B>0</B></tintColor>
            </crop>
          </TerrainFeature></value>
        </item>
      </terrainFeatures>
      <largeTerrainFeatures />
      <resourceClumps>
        <ResourceClump>
          <tile><X>20</X><Y>20</Y></tile>
          <width>2</width><height>2</height>
          <parentSheetIndex>600</parentSheetIndex>
        </ResourceClump>
      </resourceClumps>
      <objects>
        <item>
          <key><Vector2><X>30</X><Y>30</Y></Vector2></key>
          <value><Object>
            <name>Scarecrow</name>
            <parentSheetIndex>8</parentSheetIndex>
            <type>Crafting</type>
            <flipped>false</flipped>
          </Object></value>
        </item>
        <item>
          <key><Vector2><X>31</X><Y>30</Y></Vector2></key>
          <value><Object>
            <name>Wood Fence</name>
            <parentSheetIndex>0</parentSheetIndex>
            <type>Crafting</type>
            <flipped>false</flipped>
            <whichType>1</whichType>
          </Object></value>
        </item>
      </objects>
      <characters />
    </GameLocation>
  </locations>
  <currentSeason>summer</currentSeason>
  <uniqueIDForThisGame>123456</uniqueIDForThisGame>
  <hasApplied1_3_UpdateChanges>true</hasApplied1_3_UpdateChanges>
  <whichFarm>0</whichFarm>
</SaveGame>
"""


def test_parse_minimal_save():
    parsed = parse_save_xml(MINIMAL_SAVE_XML)
    assert set(parsed.keys()) == {"summary", "farm"}

    summary = parsed["summary"]
    assert summary["uniqueIDForThisGame"] == 123456
    assert summary["currentSeason"] == "summer"
    assert summary["isV1_3OrNewer"] is True
    assert summary["player"]["name"] == "Test"
    assert summary["player"]["money"] == "1000"
    assert summary["player"]["professions"] == ["Rancher", "Tiller"]
    assert "White Chicken" in summary["animals"]

    farm = parsed["farm"]
    assert farm["mapType"] == "Default"
    assert farm["size"] == {"width": 80, "height": 65}
    assert farm["greenhouse"]["unlocked"] is True
    assert any(b["buildingType"] == "Coop" for b in farm["buildings"])
    assert any(o["displayName"] == "Scarecrow" for o in farm["objects"])

    fences = farm["fences"]
    assert len(fences) == 1
    assert fences[0]["name"] == "Fence"
    assert "orientation" in fences[0]

    crops = farm["crops"]
    assert len(crops) == 1
    assert crops[0]["currentPhase"] == 2
    assert crops[0]["rowInSpriteSheet"] == 23

    clumps = farm["resourceClumps"]
    assert clumps[0]["parentSheetIndex"] == 600


def test_store_caches_and_refreshes(tmp_path: Path):
    slot_dir = tmp_path / "Test_123456"
    slot_dir.mkdir()
    save_file = slot_dir / "Test_123456"
    save_file.write_bytes(MINIMAL_SAVE_XML)

    settings = Settings(saves_dir=tmp_path, cache_ttl_seconds=60)
    store = SaveStore(settings=settings)

    import asyncio

    entry1 = asyncio.run(store.get("Test_123456"))
    entry2 = asyncio.run(store.get("Test_123456"))
    assert entry1.parsed_at == entry2.parsed_at  # cache hit

    entry3 = asyncio.run(store.get("Test_123456", force_refresh=True))
    assert entry3.parsed_at >= entry1.parsed_at

    slots = store.list_slots()
    assert len(slots) == 1
    assert slots[0]["slot"] == "Test_123456"
    assert "summary" in entry3.data and "farm" in entry3.data


def test_api_endpoints(tmp_path: Path, monkeypatch):
    slot_dir = tmp_path / "Test_123456"
    slot_dir.mkdir()
    (slot_dir / "Test_123456").write_bytes(MINIMAL_SAVE_XML)

    monkeypatch.setenv("JUNIMO_SAVES_DIR", str(tmp_path))
    from app.config import get_settings

    get_settings.cache_clear()

    app = create_app()
    with TestClient(app) as client:
        r = client.get("/healthz")
        assert r.status_code == 200
        assert r.json()["saves_dir_exists"] is True

        r = client.get("/saves")
        assert r.status_code == 200
        slots = r.json()["slots"]
        assert any(s["slot"] == "Test_123456" for s in slots)

        # Summary view (PROTOCOL §2.3)
        r = client.get("/saves/Test_123456")
        assert r.status_code == 200
        body = r.json()
        assert body["data"]["player"]["name"] == "Test"
        assert "dateString" in body["data"]
        assert "farm" not in body["data"]

        # Farm view (PROTOCOL §2.4)
        r = client.get("/saves/Test_123456/farm")
        assert r.status_code == 200
        farm = r.json()["data"]
        assert farm["mapType"] == "Default"
        assert isinstance(farm["objects"], list)
        assert "size" in farm

        # Full view (PROTOCOL §2.6)
        r = client.get("/saves/Test_123456/full")
        assert r.status_code == 200
        full = r.json()["data"]
        assert "summary" in full and "farm" in full
        assert full["summary"]["player"]["name"] == "Test"
        assert full["farm"]["mapType"] == "Default"

        r = client.post("/saves/Test_123456/refresh")
        assert r.status_code == 200
        assert r.json()["data"]["player"]["name"] == "Test"

        r = client.post("/refresh")
        assert r.status_code == 200
        assert any(item["slot"] == "Test_123456" for item in r.json()["results"])

    get_settings.cache_clear()


def test_token_gate(tmp_path: Path, monkeypatch):
    slot_dir = tmp_path / "Test_123456"
    slot_dir.mkdir()
    (slot_dir / "Test_123456").write_bytes(MINIMAL_SAVE_XML)

    monkeypatch.setenv("JUNIMO_SAVES_DIR", str(tmp_path))
    monkeypatch.setenv("JUNIMO_API_TOKEN", "secret")
    from app.config import get_settings

    get_settings.cache_clear()

    app = create_app()
    with TestClient(app) as client:
        r = client.post("/refresh")
        assert r.status_code == 401

        r = client.post("/refresh", headers={"Authorization": "Bearer secret"})
        assert r.status_code == 200

        # Read endpoints stay open even with token enabled.
        r = client.get("/saves/Test_123456/farm")
        assert r.status_code == 200

    get_settings.cache_clear()


def test_404_on_missing_slot(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("JUNIMO_SAVES_DIR", str(tmp_path))
    from app.config import get_settings

    get_settings.cache_clear()
    app = create_app()
    with TestClient(app) as client:
        for path in ("/saves/Nope", "/saves/Nope/farm", "/saves/Nope/full"):
            r = client.get(path)
            assert r.status_code == 404, path
    get_settings.cache_clear()
