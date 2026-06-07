from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    PROJECT_NAME: str = "TurtleNet"
    VERSION: str = "0.1.0"
    API_V1_STR: str = "/api/v1"
    ALLOWED_ORIGINS: list[str] = ["http://0.0.0.0:8000"]

    class Config:
        env_file = ".env"


settings = Settings()
