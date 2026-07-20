from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.db import SessionLocal


def get_session() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session


SessionDependency = Annotated[Session, Depends(get_session)]
