"""
Captive Portal service configuration.
All values come from environment variables (never hardcoded).
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Service
    debug: bool = False
    portal_host: str = "0.0.0.0"
    portal_port: int = 8001
    portal_secret_key: str  # JWT signing key — must be set in env

    # Postgres (async via asyncpg)
    postgres_host: str = "db"
    postgres_port: int = 5432
    postgres_db: str = "netsuite_isp"
    postgres_user: str = "netsuite"
    postgres_password: str

    # RADIUS database (sync via psycopg2 — same DB host, different database)
    radius_db_user: str = "radius"
    radius_db_password: str = "devpassword"

    # Redis
    redis_url: str = "redis://redis:6379/0"

    # M-Pesa
    mpesa_environment: str = "sandbox"
    mpesa_consumer_key: str = ""
    mpesa_consumer_secret: str = ""
    mpesa_shortcode: str = "174379"
    mpesa_passkey: str = ""
    mpesa_callback_base_url: str = "https://localhost"

    # CORS
    allowed_origins: List[str] = ["*"]

    @property
    def async_database_url(self) -> str:
        """Plain asyncpg DSN — NOT the SQLAlchemy +asyncpg variant."""
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


settings = Settings()
