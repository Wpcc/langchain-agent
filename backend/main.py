from contextlib import asynccontextmanager

# Load .env before any LangChain import so LANGSMITH_* vars reach the SDK
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(dotenv_path=Path(__file__).parent / ".env", override=False)

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from backend.api.routes import auth, chat, documents
from backend.core.limiter import limiter
from backend.db.session import create_tables


@asynccontextmanager
async def lifespan(app: FastAPI):
    from backend.utils.config_handler import settings
    from backend.utils.logger_handler import logger
    import os

    create_tables()

    # Warn if CODE model is still set to the API key value
    if settings.DOUBAO_MODEL_CODE == settings.DOUBAO_API_KEY:
        logger.warning(
            "misconfiguration",
            detail="DOUBAO_MODEL_CODE equals DOUBAO_API_KEY — set it to a real endpoint ID in Ark console (模型推理 → 在线推理)",
        )

    tracing_on = os.environ.get("LANGSMITH_TRACING", "").lower() == "true"
    logger.info(
        "startup",
        langsmith_tracing=tracing_on,
        langsmith_project=os.environ.get("LANGCHAIN_PROJECT", "—"),
    )

    yield


app = FastAPI(
    title="智扫通智能客服 API",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/auth", tags=["认证"])
app.include_router(chat.router, prefix="/api/chat", tags=["对话"])
app.include_router(documents.router, prefix="/api/documents", tags=["文档"])


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors(), "message": "请求参数验证失败"},
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    from backend.utils.logger_handler import logger
    logger.error("unhandled_exception", path=str(request.url), error=str(exc))
    return JSONResponse(status_code=500, content={"detail": "服务器内部错误"})


@app.get("/api/health")
def health_check():
    return {"status": "ok", "service": "智扫通智能客服"}
