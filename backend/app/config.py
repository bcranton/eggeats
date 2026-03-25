from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Database
    database_url: str

    # LLM
    anthropic_api_key: str

    # YouTube Data API v3
    youtube_api_key: str

    # Google Places API (geocoding / business resolution)
    google_places_api_key: str

    # Mapbox access token (sent to frontend for map rendering)
    mapbox_access_token: str

    # Google OAuth
    google_client_id: str
    google_client_secret: str
    google_redirect_uri: str = "http://localhost:8000/auth/callback"

    # Admin access control (comma-separated emails) — set via ADMIN_EMAILS env var
    admin_emails: str

    # Session signing
    secret_key: str

    # App
    environment: str = "development"
    log_level: str = "INFO"

    @property
    def admin_email_list(self) -> list[str]:
        return [e.strip().lower() for e in self.admin_emails.split(",")]

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
