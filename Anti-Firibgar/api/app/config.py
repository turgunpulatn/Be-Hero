from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://anti:anti@localhost:5432/antifiribgar"
    jwt_secret: str = "dev-secret-change-me"
    jwt_days: int = 30
    cookie_secure: bool = False

    # Demo mode: OTP code is returned in the API response and shown on screen (no real SMS).
    dev_mode: bool = True
    otp_ttl_seconds: int = 300
    otp_resend_seconds: int = 30
    otp_max_attempts: int = 5

    free_reviews: int = 3
    package_reviews: int = 10
    package_price_uzs: int = 25000

    upload_dir: str = "./data/uploads"
    max_upload_mb: int = 15
    ocr_langs: str = "uzb+rus+eng"

    # AI: "mock" (keyword rules), "ollama" (Ollama API) or "openai" (LM Studio, llama.cpp, vLLM...).
    ai_provider: str = "mock"
    ai_base_url: str = "http://localhost:11434"
    ai_model: str = "gemma3:4b"
    ai_api_key: str = ""
    ai_timeout_seconds: int = 300

    cors_origins: str = "http://localhost:5173,http://localhost:8080"


settings = Settings()
