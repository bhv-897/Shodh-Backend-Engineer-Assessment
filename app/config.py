from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    database_url: str = "mysql+pymysql://ease:ease@127.0.0.1:3306/easecoding?charset=utf8mb4"
    jwt_secret: str = "development-only-change-me"
    jwt_expiry_minutes: int = 60
    enable_dev_endpoints: bool = False
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

settings = Settings()
