from sqlalchemy import create_engine, make_url
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


database_url = make_url(get_settings().database_url)
if database_url.get_backend_name() == "postgresql" and "connect_timeout" not in database_url.query:
    database_url = database_url.update_query_dict({"connect_timeout": "5"})
engine = create_engine(database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)


def get_db():
    with SessionLocal() as session:
        yield session
