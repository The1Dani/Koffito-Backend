import os
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

# TODO: Needs to be tought more of how we should proceed with this kind of variables
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./koffito.db")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
