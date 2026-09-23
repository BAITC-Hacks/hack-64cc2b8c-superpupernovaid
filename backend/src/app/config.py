from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.audio.config import AudioProcessingConfig

ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")
    ai_mode: Literal["mock", "openai"] = "mock"
    openai_api_key: SecretStr = SecretStr("")
    openai_model: str = "gpt-4.1-mini"
    agent_timeout_seconds: int = 120
    database_url: str = "postgresql+psycopg://app:app@localhost:5432/app"
    redis_url: str = "redis://localhost:6379/0"
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:8080"]
    s3_endpoint_url: str = "http://localhost:9000"
    s3_access_key: SecretStr = SecretStr("minioadmin")
    s3_secret_key: SecretStr = SecretStr("minioadmin")
    s3_bucket: str = "prototype"
    media_max_file_size_bytes: int = Field(default=5 * 1024**3, ge=1)
    media_allowed_formats: list[Literal["wav", "mp3", "flac", "ogg", "mov", "matroska"]] = [
        "wav",
        "mp3",
        "flac",
        "ogg",
        "mov",
        "matroska",
    ]
    media_upload_dir: Path = ROOT / "data" / "media"
    media_ffprobe_timeout_seconds: float = Field(default=15, gt=0)
    media_ffprobe_executable: str = "ffprobe"
    media_max_concurrent_uploads: int = Field(default=2, ge=1, le=8)
    audio_target_sample_rate: int = 16000
    audio_target_channels: int = 1
    audio_target_codec: str = "pcm_s16le"
    audio_target_format: str = "wav"
    audio_ffmpeg_timeout_seconds: float = Field(default=900, gt=0)
    audio_ffmpeg_executable: str = "ffmpeg"
    audio_max_concurrent_processes: int = Field(default=1, ge=1, le=8)

    @property
    def audio_processing_config(self) -> AudioProcessingConfig:
        return AudioProcessingConfig(
            sample_rate=self.audio_target_sample_rate,
            channels=self.audio_target_channels,
            codec=self.audio_target_codec,
            format=self.audio_target_format,
        )

    @field_validator("media_upload_dir")
    @classmethod
    def absolute_media_directory(cls, value: Path) -> Path:
        return value if value.is_absolute() else ROOT / value

    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_from: str = "noreply@example.test"
    smtp_user: str = ""
    smtp_password: SecretStr = SecretStr("")
    smtp_starttls: bool = False

    @model_validator(mode="after")
    def validate_ai(self):
        self.audio_processing_config  # Validate audio format combinations at startup.
        if self.ai_mode == "openai" and not self.openai_api_key.get_secret_value():
            raise ValueError("OPENAI_API_KEY is required when AI_MODE=openai")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
