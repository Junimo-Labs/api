"""Cache + filesystem watcher for parsed saves.

Caching strategy:
- Key by slot name (the directory name under saves_dir).
- Each cache entry stores: parsed dict, source mtime, parsed_at timestamp,
  source size, source path.
- A read is served from cache iff: file mtime+size unchanged AND age <= TTL.
- Cache entries are evicted when the slot directory disappears.
- Refresh re-parses regardless of cache state.

We use `asyncio.Lock` per slot so concurrent refreshes don't double-parse.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from .config import Settings
from .parser.dates import format_date, get_date_data, preprocess_data
from .parser.savefile import parse_save_file


@dataclass
class SaveCacheEntry:
    slot: str
    source_path: str
    source_mtime: float
    source_size: int
    parsed_at: float
    data: dict
    parse_duration_ms: float


@dataclass
class SaveStore:
    settings: Settings
    _entries: Dict[str, SaveCacheEntry] = field(default_factory=dict)
    _locks: Dict[str, asyncio.Lock] = field(default_factory=dict)
    _global_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def _slot_lock(self, slot: str) -> asyncio.Lock:
        lock = self._locks.get(slot)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[slot] = lock
        return lock

    def _resolve_save_path(self, slot: str) -> Path:
        base = self.settings.saves_dir
        slot_dir = (base / slot).resolve()
        # Reject path traversal: slot must stay under saves_dir.
        if base.resolve() not in slot_dir.parents and slot_dir != base.resolve():
            raise FileNotFoundError(f"Slot {slot!r} not found")
        if not slot_dir.is_dir():
            raise FileNotFoundError(f"Slot {slot!r} not found")

        # The actual save XML in vanilla SDV is named after the slot folder
        # (e.g. Junimo_123456789/Junimo_123456789). SaveGameInfo is a smaller
        # metadata file we ignore here.
        candidate = slot_dir / slot
        if candidate.is_file():
            return candidate

        # Fallback: pick the largest non-SaveGameInfo regular file in the dir.
        candidates = [
            p for p in slot_dir.iterdir()
            if p.is_file() and p.name not in ("SaveGameInfo",)
        ]
        if not candidates:
            raise FileNotFoundError(f"No save file in slot {slot!r}")
        candidates.sort(key=lambda p: p.stat().st_size, reverse=True)
        return candidates[0]

    def list_slots(self) -> List[dict]:
        base = self.settings.saves_dir
        if not base.exists():
            return []
        out = []
        for child in sorted(base.iterdir()):
            if not child.is_dir():
                continue
            try:
                save_path = self._resolve_save_path(child.name)
            except FileNotFoundError:
                continue
            stat = save_path.stat()
            cached = self._entries.get(child.name)
            out.append(
                {
                    "slot": child.name,
                    "source_path": str(save_path),
                    "source_mtime": stat.st_mtime,
                    "source_size": stat.st_size,
                    "cached": cached is not None,
                    "cache_fresh": (
                        cached is not None
                        and cached.source_mtime == stat.st_mtime
                        and cached.source_size == stat.st_size
                        and (time.time() - cached.parsed_at)
                        <= self.settings.cache_ttl_seconds
                    ),
                }
            )
        return out

    async def get(self, slot: str, *, force_refresh: bool = False) -> SaveCacheEntry:
        lock = self._slot_lock(slot)
        async with lock:
            save_path = self._resolve_save_path(slot)
            stat = save_path.stat()
            cached = self._entries.get(slot)
            if (
                not force_refresh
                and cached is not None
                and cached.source_mtime == stat.st_mtime
                and cached.source_size == stat.st_size
                and (time.time() - cached.parsed_at)
                <= self.settings.cache_ttl_seconds
            ):
                return cached

            started = time.perf_counter()
            data = await asyncio.to_thread(
                parse_save_file, save_path, self.settings.max_save_bytes
            )
            duration_ms = (time.perf_counter() - started) * 1000.0

            data["dateString"] = self._build_date_string(data)

            entry = SaveCacheEntry(
                slot=slot,
                source_path=str(save_path),
                source_mtime=stat.st_mtime,
                source_size=stat.st_size,
                parsed_at=time.time(),
                data=data,
                parse_duration_ms=duration_ms,
            )
            self._entries[slot] = entry
            return entry

    async def refresh_all(self) -> List[dict]:
        """Re-parse every slot. Returns per-slot status."""
        async with self._global_lock:
            results = []
            for info in self.list_slots():
                slot = info["slot"]
                try:
                    entry = await self.get(slot, force_refresh=True)
                    results.append(
                        {
                            "slot": slot,
                            "ok": True,
                            "parsed_at": entry.parsed_at,
                            "parse_duration_ms": entry.parse_duration_ms,
                        }
                    )
                except Exception as exc:  # noqa: BLE001 - surface parser errors
                    results.append({"slot": slot, "ok": False, "error": str(exc)})
            self._evict_missing()
            return results

    def _evict_missing(self) -> None:
        live = {info["slot"] for info in self.list_slots()}
        for slot in list(self._entries.keys()):
            if slot not in live:
                self._entries.pop(slot, None)
                self._locks.pop(slot, None)

    @staticmethod
    def _build_date_string(data: dict) -> Optional[str]:
        player = data.get("player") or {}
        try:
            day = player.get("dayOfMonthForSaveGame")
            season = player.get("seasonForSaveGame")
            year = player.get("yearForSaveGame")
            if day is not None and season is not None and year is not None:
                normalized = preprocess_data(
                    {
                        "dayOfMonthForSaveGame": str(day),
                        "seasonForSaveGame": str(season),
                        "yearForSaveGame": str(year),
                    }
                )
                return format_date(
                    normalized["dayOfMonthForSaveGame"],
                    normalized["seasonForSaveGame"],
                    normalized["yearForSaveGame"],
                )
            stats = player.get("stats") or {}
            days_played = stats.get("DaysPlayed")
            if days_played is not None:
                return format_date(*get_date_data(int(days_played)))
        except (TypeError, ValueError):
            return None
        return None
