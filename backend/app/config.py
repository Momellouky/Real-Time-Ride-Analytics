from pathlib import Path

from pydantic import AnyHttpUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    pinot_broker_url: AnyHttpUrl = "http://localhost:8099"
    pinot_query_timeout_seconds: float = Field(default=3.0, gt=0)
    kafka_bootstrap_servers: str = "localhost:9092"
    kafka_topic: str = Field(default="ride-metrics-snapshots", min_length=1)
    kafka_publish_timeout_seconds: float = Field(default=10.0, gt=0)

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env", extra="ignore"
    )
