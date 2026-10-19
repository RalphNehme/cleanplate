from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://cleanplate:cleanplate@localhost:5433/cleanplate"
    socrata_app_token: str = ""
    report_salt: str = "dev-only-salt"
    anthropic_api_key: str = ""


settings = Settings()
