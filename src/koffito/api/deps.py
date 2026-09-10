from fastapi import Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..services import ItemService


def get_item_service(db: Session = Depends(get_db)) -> ItemService:
    return ItemService(db)
