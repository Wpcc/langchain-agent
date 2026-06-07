import asyncio
import os
from pathlib import Path

from fastapi import APIRouter, Body, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from backend.core.dependencies import get_current_user
from backend.db.models import User
from backend.utils.config_handler import chroma_config
from backend.utils.file_handler import (
    get_file_md5_hex,
    get_abs_path,
    listdir_with_allowed_type,
    remove_md5_hex,
)

router = APIRouter()

_ALLOWED = {".txt", ".pdf"}
_DATA_PATH = lambda: Path(get_abs_path(chroma_config["data_path"]))


# ── Schemas ─────────────────────────────────────────────────────────────────

class DocumentInfo(BaseModel):
    filename: str
    filepath: str
    size_kb: float
    indexed: bool
    chunks: int


class RetrievalChunk(BaseModel):
    rank: int
    content: str
    source: str


class RetrievalResult(BaseModel):
    original_query: str
    rewritten_query: str
    chunks: list[RetrievalChunk]


# ── Helpers ──────────────────────────────────────────────────────────────────

def _get_vs():
    from backend.rag.vector_store import VectorStoreService
    return VectorStoreService()


def _get_rag():
    from backend.rag.rag_service import RagSummarizeService
    return RagSummarizeService()


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("", response_model=list[DocumentInfo])
def list_documents(user: User = Depends(get_current_user)):
    """List all files in the data/ folder with their indexing status."""
    vs = _get_vs()
    indexed_sources = {item["path"]: item["chunks"] for item in vs.list_sources()}

    data_dir = _DATA_PATH()
    results: list[DocumentInfo] = []

    for path in sorted(data_dir.iterdir()):
        if path.suffix.lower().lstrip(".") not in {e.lstrip(".") for e in _ALLOWED}:
            continue
        full = str(path.resolve())
        chunks = indexed_sources.get(full, 0)
        results.append(DocumentInfo(
            filename=path.name,
            filepath=full,
            size_kb=round(path.stat().st_size / 1024, 1),
            indexed=full in indexed_sources,
            chunks=chunks,
        ))

    return results


@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
):
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in _ALLOWED:
        raise HTTPException(400, f"仅支持 {', '.join(_ALLOWED)} 格式")

    dest = _DATA_PATH() / file.filename
    dest.write_bytes(await file.read())
    return {"message": f"文件 {file.filename} 已上传，点击「建立索引」使其生效"}


@router.post("/index")
async def index_documents(user: User = Depends(get_current_user)):
    """Scan data/ and embed all files not yet in the vector store."""
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, lambda: _get_vs().load_document())
    return {"message": "索引构建完成"}


@router.delete("/{filename}", status_code=204)
def delete_document(filename: str, user: User = Depends(get_current_user)):
    """Delete a document from disk and remove its vectors from ChromaDB."""
    dest = _DATA_PATH() / filename
    if not dest.exists():
        raise HTTPException(404, f"文件 {filename} 不存在")

    md5 = get_file_md5_hex(str(dest))

    # Remove vectors from ChromaDB
    vs = _get_vs()
    vs.delete_source(str(dest.resolve()))

    # Remove MD5 record so it can be re-indexed if re-uploaded
    if md5:
        remove_md5_hex(md5, chroma_config["md5_hex_store"])

    # Delete physical file
    dest.unlink()


@router.post("/test-retrieval", response_model=RetrievalResult)
async def test_retrieval(
    query: str = Body(..., embed=True),
    user: User = Depends(get_current_user),
):
    """Run a query through the full pipeline (rewrite → BM25+vector → reranker)
    and return the ranked chunks. Used by the knowledge management UI.
    """
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, lambda: _get_rag().test_retrieval(query))
    return RetrievalResult(
        original_query=result["original_query"],
        rewritten_query=result["rewritten_query"],
        chunks=[RetrievalChunk(**c) for c in result["chunks"]],
    )
