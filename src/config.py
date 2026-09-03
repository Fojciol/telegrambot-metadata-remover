from pathlib import Path
from typing import Any, Set
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    bot_token: str
    allowed_user_ids: Set[int] = set()
    temp_dir: Path = Path("/tmp/bot_media")
    max_file_size_mb: int = 20

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @field_validator("allowed_user_ids", mode="before")
    @classmethod
    def parse_allowed_user_ids(cls, v: Any) -> Set[int]:
        if isinstance(v, str):
            clean_str = v.strip()
            if not clean_str:
                return set()
            ids = set()
            for part in clean_str.split(","):
                part = part.strip()
                if part and part.lstrip("-").isdigit():
                    ids.add(int(part))
            return ids
        if isinstance(v, (list, tuple, set)):
            return {int(x) for x in v if str(x).strip().lstrip("-").isdigit()}
        return set()

    @field_validator("temp_dir", mode="after")
    @classmethod
    def ensure_temp_dir(cls, v: Path) -> Path:
        v.mkdir(parents=True, exist_ok=True)
        return v


def get_settings() -> Settings:
    return Settings()
