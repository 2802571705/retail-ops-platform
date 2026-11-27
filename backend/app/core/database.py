import os
from pathlib import Path
from urllib.parse import quote

from dotenv import load_dotenv
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

engine = create_engine(url, pool_pre_ping=True)


def get_db():
    with Session(engine) as session:
        yield session
