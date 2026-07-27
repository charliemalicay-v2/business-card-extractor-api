from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/business_cards"
    llm_model_path: str = "./models/model.gguf"
    max_upload_size_bytes: int = 10 * 1024 * 1024
    allowed_image_content_types: str = "image/jpeg,image/png"
    ocr_min_text_length: int = 10
    cors_allowed_origins: str = "http://localhost:3000"

    image_storage_backend: str = "local"
    image_storage_local_dir: str = "./data/images"
    image_storage_url_ttl_seconds: int = 3600

    aws_s3_bucket: str = ""
    aws_region: str = ""
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""

    supabase_url: str = ""
    supabase_service_key: str = ""
    supabase_storage_bucket: str = ""
    supabase_storage_public: bool = False

    @property
    def allowed_content_types(self) -> list[str]:
        return [t.strip() for t in self.allowed_image_content_types.split(",") if t.strip()]

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]


settings = Settings()
