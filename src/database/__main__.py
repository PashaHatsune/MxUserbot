from sqlalchemy import JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase): 
    pass


class Settings(Base):
    __tablename__ = "settings"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    owner: Mapped[str] = mapped_column(index=True)
    key: Mapped[str] = mapped_column(index=True)
    value: Mapped[str] = mapped_column(JSON)