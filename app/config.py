from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/business_cards"
    llm_model_path: str = "./models/model.gguf"
    max_upload_size_bytes: int = 10 * 1024 * 1024
    allowed_image_content_types: str = "image/jpeg,image/png"
    ocr_min_text_length: int = 10

    @property
    def allowed_content_types(self) -> list[str]:
        return [t.strip() for t in self.allowed_image_content_types.split(",") if t.strip()]


settings = Settings()
