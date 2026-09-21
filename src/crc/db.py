"""Acces a la base PostgreSQL."""
from functools import lru_cache

import pandas as pd
from sqlalchemy import Engine, create_engine, text

from crc.config import get_settings


@lru_cache
def get_engine() -> Engine:
    return create_engine(get_settings().database_url, pool_pre_ping=True)


def read_sql(query: str, **params) -> pd.DataFrame:
    return pd.read_sql(text(query), get_engine(), params=params)


def execute(statement: str, **params) -> None:
    with get_engine().begin() as conn:
        conn.execute(text(statement), params)


def check_connection() -> bool:
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False