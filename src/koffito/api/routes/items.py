from fastapi import APIRouter, Depends, HTTPException

from ...schemas import ItemCreate, ItemOut
from ...services import ItemNotFound, ItemService
from ..deps import get_item_service

router = APIRouter(prefix="/items", tags=["items"])


@router.post("", response_model=ItemOut)
def create_item(item: ItemCreate, service: ItemService = Depends(get_item_service)):
    return service.create_item(item.name)


@router.get("", response_model=list[ItemOut])
def list_items(service: ItemService = Depends(get_item_service)):
    return service.list_items()


@router.get("/{item_id}", response_model=ItemOut)
def read_item(item_id: int, service: ItemService = Depends(get_item_service)):
    try:
        return service.get_item(item_id)
    except ItemNotFound:
        raise HTTPException(status_code=404, detail="Item not found")
