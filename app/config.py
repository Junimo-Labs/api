from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="JUNIMO_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    saves_dir: Path = Field(
        default=Path("/saves"),
        description="Root directory containing Stardew Valley save folders.",
    )
    cache_ttl_seconds: int = Field(
        default=300,
        description=(
            "Soft TTL for the parsed cache. Cache also invalidates on save mtime "
            "change; this is just an upper bound."
        ),
    )
    max_save_bytes: int = Field(
        default=64 * 1024 * 1024,
        description="Refuse to parse save XML files larger than this.",
    )
    api_token: str | None = Field(
        default=None,
        description=(
            "Optional bearer token. When set, mutating endpoints require "
            "Authorization: Bearer <token>."
        ),
    )
    save_filename_candidates: List[str] = Field(
        default_factory=lambda: ["SaveGameInfo", ""],
        description=(
            "Filenames inside a slot directory to consider; empty string means "
            "the file with the same name as the slot directory (default SDV layout)."
        ),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
