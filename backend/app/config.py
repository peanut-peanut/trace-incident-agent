from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    app_mode: Literal["demo", "live"] = "demo"
    database_url: str = "sqlite:///./data/app.db"
    checkpoint_url: str = "./data/checkpoints.db"
    llm_provider: Literal["generic", "deepseek"] = "generic"
    llm_base_url: str = ""
    llm_api_key: str = Field(default="", repr=False)
    llm_model: str = ""
    max_model_rounds: int = Field(default=6, ge=1, le=12)
    max_tool_calls: int = Field(default=10, ge=1, le=20)
    request_timeout: float = Field(default=30, ge=1, le=120)
    console_token: str = ""

    def prepare(self):
        Path("data").mkdir(exist_ok=True)
        if not self.checkpoint_url.startswith("postgres"):
            Path(self.checkpoint_url).parent.mkdir(parents=True, exist_ok=True)
        if self.app_mode == "live":
            if not all([self.llm_base_url, self.llm_api_key, self.llm_model]):
                raise ValueError("Live mode requires LLM_BASE_URL, LLM_API_KEY and LLM_MODEL")
            if not self.llm_base_url.startswith("https://"):
                raise ValueError("LLM_BASE_URL must use HTTPS")
