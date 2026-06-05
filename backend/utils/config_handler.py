import yaml
from dotenv import load_dotenv
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

from backend.utils.path_tool import get_abs_path

# Load .env into os.environ so LangChain/LangSmith can pick up LANGCHAIN_* vars
load_dotenv(override=False)


class Settings(BaseSettings):
    # LLM
    DOUBAO_API_KEY: str
    DOUBAO_BASE_URL: str
    DOUBAO_MODEL: str
    # Embeddings
    EMBEDDING_MODEL: str
    EMBEDDING_API_KEY: str
    # Database
    DATABASE_URL: str = "sqlite:///./zhisaotong.db"
    # Redis
    REDIS_URL: str = "redis://localhost:6379"
    # JWT
    JWT_SECRET_KEY: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60
    # Tavily search
    TAVILY_API_KEY: str = ""
    # LangSmith tracing (optional)
    LANGSMITH_TRACING: bool = True
    LANGSMITH_API_KEY: str = ""
    LANGCHAIN_PROJECT: str = "zhisaotong-dev"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

# Backward-compatible dict — existing code (model/factory.py etc.) unchanged
rag_config = {
    "DOUBAO_API_KEY": settings.DOUBAO_API_KEY,
    "DOUBAO_BASE_URL": settings.DOUBAO_BASE_URL,
    "DOUBAO_MODEL": settings.DOUBAO_MODEL,
    "EMBEDDING_MODEL": settings.EMBEDDING_MODEL,
    "EMBEDDING_API_KEY": settings.EMBEDDING_API_KEY,
}


def load_config(config_path: str, encoding: str = "utf-8"):
    with open(config_path, "r", encoding=encoding) as f:
        return yaml.load(f, Loader=yaml.FullLoader)


chroma_config = load_config(config_path=get_abs_path("config/chroma.yml"))
prompts_config = load_config(config_path=get_abs_path("config/prompts.yml"))
agent_config = load_config(config_path=get_abs_path("config/agent.yml"))

if __name__ == "__main__":
    print(settings.model_dump())