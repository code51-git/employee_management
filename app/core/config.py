# app/core/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import computed_field

class Settings(BaseSettings):
    PROJECT_NAME: str = "Employee Management System"
    ENVIRONMENT: str = "development"
    API_V1_STR: str = "/api/v1"
    SECRET_KEY: str = "super-secret-random-string-change-in-prod"
    
    # Database 
    POSTGRES_SERVER: str = "postgres"
    POSTGRES_USER: str = "employee_postgres"
    POSTGRES_PASSWORD: str = "secure_db_password"
    POSTGRES_DB: str = "employee_management_system"
    POSTGRES_PORT: int = 5432

    # Redis 
    REDIS_HOST: str = "redis"
    REDIS_PORT: int = 6379

    # JWT Settings
    SECRET_KEY: str = "super-secret-random-string-change-in-prod"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60      
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7 

    #sms
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = "your-system-email@gmail.com"
    SMTP_PASSWORD: str = "your-secure-app-password"
    EMAILS_FROM: str = "noreply@company.com"         

    @computed_field
    @property
    def DATABASE_URL(self) -> str:
        return f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

    model_config = SettingsConfigDict(
        env_file=".env", 
        env_file_encoding="utf-8", 
        case_sensitive=True,
        extra="ignore"
    )

settings = Settings()


