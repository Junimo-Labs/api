"""Smoke tests for the parser layer.

These don't assert business semantics (real save XML is large); they just
ensure the parser, store, and API wiring don't trip on minimal valid XML.
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
    <mailReceived />
  </player>
  <farmerFriendships />
  <locations>
    <GameLocation xsi:type="Farm">
      <buildings />
      <terrainFeatures />
      <largeTerrainFeatures />
      <resourceClumps />
      <objects />
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
    assert parsed["uniqueIDForThisGame"] == 123456
    assert parsed["currentSeason"] == "summer"
    assert parsed["isV1_3OrNewer"] is True
    assert parsed["player"]["name"] == "Test"
    assert parsed["player"]["money"] == "1000"
    assert parsed["player"]["professions"] == ["Rancher", "Tiller"]


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

        r = client.get("/saves/Test_123456")
        assert r.status_code == 200
        body = r.json()
        assert body["data"]["player"]["name"] == "Test"
        assert "dateString" in body["data"]

        r = client.post("/saves/Test_123456/refresh")
        assert r.status_code == 200

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

        r = client.post(
            "/refresh", headers={"Authorization": "Bearer secret"}
        )
        assert r.status_code == 200

    get_settings.cache_clear()
