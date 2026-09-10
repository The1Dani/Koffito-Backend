from sqlalchemy.orm import Session

from ..models import Item


class ItemRepository:
    """Raw DB access for Item — no validation, no business rules."""

    def __init__(self, db: Session):
        self.db = db

    def create(self, name: str) -> Item:
        item = Item(name=name)
        self.db.add(item)
        self.db.commit()
        self.db.refresh(item)
        return item

    def get(self, item_id: int) -> Item | None:
        return self.db.get(Item, item_id)

    def list(self) -> list[Item]:
        return self.db.query(Item).all()
