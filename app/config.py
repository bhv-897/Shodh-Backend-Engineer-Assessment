from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import model_validator

class Settings(BaseSettings):
    database_url: str = "mysql+pymysql://ease:ease@127.0.0.1:3306/easecoding?charset=utf8mb4"
    jwt_secret: str = "development-only-change-me"
    environment: str = "production"
    jwt_expiry_minutes: int = 60
    enable_dev_endpoints: bool = False
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    @model_validator(mode="after")
    def validate_jwt_secret(self):
        if self.environment.lower() != "development" and (
            self.jwt_secret == "development-only-change-me" or len(self.jwt_secret) < 32
        ):
            raise ValueError("JWT_SECRET must be at least 32 characters and not the development fallback")
        return self

settings = Settings()
