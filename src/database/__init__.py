from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from .__main__ import Base

class AsyncSessionWrapper:
    def __init__(self, url="sqlite+aiosqlite:///sekai.db"):
        self.engine = create_async_engine(url, echo=False, future=True)
        self.async_session = sessionmaker(
            self.engine, expire_on_commit=False, class_=AsyncSession
        )

        for mapper in Base.registry.mappers:
            cls = mapper.class_
            setattr(self, cls.__name__, cls)

    async def init_db(self):
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)


    async def get_db(self):
        async with self.async_session() as session:
            yield session

session = AsyncSessionWrapper()


