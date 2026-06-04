import os
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from backend.core.dependencies import get_current_user
from backend.db.models import User
from utils.path_tool import get_abs_path

router = APIRouter()

_ALLOWED = {".txt", ".pdf"}


@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
):
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in _ALLOWED:
        raise HTTPException(400, f"仅支持 {', '.join(_ALLOWED)} 格式")

    dest = Path(get_abs_path("data")) / file.filename
    dest.write_bytes(await file.read())

    return {"message": f"文件 {file.filename} 已上传，将在知识库重建后生效"}
