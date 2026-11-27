import os
from pathlib import Path
from urllib.parse import quote

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import create_engine, pool

load_dotenv(Path(__file__).resolve().parents[2] / '.env')

url = os.getenv('DATABASE_URL')
if not url:
    user = quote(os.environ['POSTGRES_USER'], safe='')
    password = quote(os.environ['POSTGRES_PASSWORD'], safe='')
    name = quote(os.environ['POSTGRES_DB'], safe='')
    port = os.getenv('POSTGRES_PORT', '5432')
    url = f'postgresql+psycopg://{user}:{password}@127.0.0.1:{port}/{name}'

if context.is_offline_mode():
    context.configure(url=url, literal_binds=True, dialect_opts={'paramstyle': 'named'})
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=None)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()
