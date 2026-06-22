import yaml
from dotenv import load_dotenv
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

from backend.utils.path_tool import get_abs_path, get_project_root

# .env lives inside backend/ — resolve via absolute path so it is found
# regardless of which directory uvicorn / pytest is launched from.
_ENV_FILE = get_abs_path(".env")
load_dotenv(dotenv_path=_ENV_FILE, override=False)


class Settings(BaseSettings):
    # LLM — shared credentials
    DOUBAO_API_KEY: str
    DOUBAO_BASE_URL: str
    # Model roster (rule-based routing in model/factory.py)
    DOUBAO_MODEL_PRO: str   # main agent, complex reasoning
    DOUBAO_MODEL_MINI: str  # RAG summarization, structured tasks
    DOUBAO_MODEL_LITE: str  # simple / high-frequency tasks
    DOUBAO_MODEL_CODE: str  # code generation / analysis
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
    # OpenTelemetry (optional) — set to OTLP HTTP endpoint to enable
    # e.g. http://localhost:4318 for a local Jaeger / Grafana Tempo instance
    OTEL_ENDPOINT: str = ""

    model_config = SettingsConfigDict(env_file=_ENV_FILE, env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

rag_config = {
    "DOUBAO_API_KEY":    settings.DOUBAO_API_KEY,
    "DOUBAO_BASE_URL":   settings.DOUBAO_BASE_URL,
    "DOUBAO_MODEL_PRO":  settings.DOUBAO_MODEL_PRO,
    "DOUBAO_MODEL_MINI": settings.DOUBAO_MODEL_MINI,
    "DOUBAO_MODEL_LITE": settings.DOUBAO_MODEL_LITE,
    "DOUBAO_MODEL_CODE": settings.DOUBAO_MODEL_CODE,
    "EMBEDDING_MODEL":   settings.EMBEDDING_MODEL,
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