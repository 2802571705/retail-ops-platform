
import os
from asyncio import Semaphore
from pathlib import Path
from urllib.parse import quote

from dotenv import load_dotenv
from fastapi import Depends
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

load_dotenv(Path(__file__).resolve().parents[3] / ".env")

url = os.getenv("DATABASE_URL")

if not url:
    user = quote(os.environ["POSTGRES_USER"], safe="")
    password = quote(os.environ["POSTGRES_PASSWORD"], safe="")
    database = quote(os.environ["POSTGRES_DB"], safe="")
    port = os.getenv("POSTGRES_PORT", "5432")
    url = f"postgresql+psycopg://{user}:{password}@127.0.0.1:{port}/{database}"

engine = create_engine(
    url,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    pool_timeout=30,
)

# 异步数据库访问准入控制
db_slots = Semaphore(12)


async def acquire_db_slot():
    async with db_slots:
        yield


def get_db(_slot: None = Depends(acquire_db_slot)):
    with Session(engine) as session:
        yield session
