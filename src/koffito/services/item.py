from sqlalchemy.orm import Session

from ..models import Item
from ..repositories import ItemRepository


class ItemNotFound(Exception):
    def __init__(self, item_id: int):
        self.item_id = item_id


class ItemService:
    """Business rules for items. Routers call this, never the repository directly."""

    def __init__(self, db: Session):
        self.repo = ItemRepository(db)

    def create_item(self, name: str) -> Item:
        return self.repo.create(name)

    def get_item(self, item_id: int) -> Item:
        item = self.repo.get(item_id)
        if item is None:
            raise ItemNotFound(item_id)
        return item

    def list_items(self) -> list[Item]:
        return self.repo.list()
