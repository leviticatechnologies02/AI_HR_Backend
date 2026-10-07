from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    PROJECT_NAME: str = "hrms-backend"
    DEBUG: bool = False

    DATABASE_URL: str
    UPLOAD_DIR: str = "uploads"
    SECRET_KEY: str

    SMTP_HOST: str
    SMTP_PORT: int
    SMTP_USERNAME: str
    SMTP_PASSWORD: str
    SMTP_FROM: str
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    AWS_REGION: str = "us-east-1"
    AWS_BUCKET_NAME: str = ""
    CLOUDFRONT_URL: str = ""
    ALGORITHM: str = "HS256"
    REDIS_URL: str = "redis://localhost:6379"

    ADMIN_USERNAME: str
    ADMIN_PASSWORD: str

   
    SCORE_THRESHOLD: float = Field(default=25.0, description="From .env; restart server after changes")
    OPENAI_API_KEY: str

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()

_WEAK_SECRETS = {"your_super_secret_key", "secret", "changeme", "change-me", "test", "testsecret"}
if settings.SECRET_KEY in _WEAK_SECRETS or len(settings.SECRET_KEY) < 32:
    import warnings
    warnings.warn(
        "SECRET_KEY is weak or a placeholder. Set a random value of 32+ characters in .env "
        "(python -c \"import secrets; print(secrets.token_urlsafe(48))\"). "
        "Anyone who knows the key can forge login tokens.",
        stacklevel=2,
    )
