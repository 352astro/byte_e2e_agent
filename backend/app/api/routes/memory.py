from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.dependencies import get_memory_service
from app.services.memory_service import MemoryService

router = APIRouter(prefix="/api/memory")


class AddMemoryRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=2000)
    kind: str = "fact"


@router.get("")
async def list_memories(
    memory_service: MemoryService = Depends(get_memory_service),
) -> dict:
    return await memory_service.list_memories()


@router.post("")
async def add_memory(
    req: AddMemoryRequest,
    memory_service: MemoryService = Depends(get_memory_service),
) -> dict:
    content = req.content.strip()
    if not content:
        raise HTTPException(status_code=422, detail="content is required")
    return await memory_service.add_memory(content, kind=req.kind)


@router.delete("/{memory_id}")
async def delete_memory(
    memory_id: str,
    memory_service: MemoryService = Depends(get_memory_service),
) -> dict:
    ok = await memory_service.delete_memory(memory_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Memory not found")
    return {"ok": True}
