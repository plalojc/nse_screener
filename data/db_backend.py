from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Sequence

import pandas as pd

from config import (
    DATABASE_URL,
    DB_BACKEND,
    DB_PATH,
    DB_SYSTEM_SCHEMA,
    DB_USER_SCHEMA,
)


IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def is_postgres() -> bool:
    return DB_BACKEND in {"postgres", "postgresql"} or DATABASE_URL.startswith(("postgres://", "postgresql://"))


def system_schema() -> str:
    return DB_SYSTEM_SCHEMA


def user_schema() -> str:
    return DB_USER_SCHEMA


def _quote_ident(identifier: str) -> str:
    if not IDENT_RE.match(identifier):
        raise ValueError(f"Unsafe SQL identifier: {identifier!r}")
    return f'"{identifier}"'


def table_name(name: str, schema: str | None = None) -> str:
    if not is_postgres():
        return name
    schema_name = schema or system_schema()
    return f"{_quote_ident(schema_name)}.{_quote_ident(name)}"


def adapt_sql(sql: str) -> str:
    if not is_postgres():
        return sql
    return sql.replace("?", "%s").replace("datetime('now')", "CURRENT_TIMESTAMP")


def connect(sqlite_path: str | Path = DB_PATH):
    if is_postgres():
        if not DATABASE_URL:
            raise RuntimeError("DATABASE_URL or POSTGRES_DSN must be set when DB_BACKEND=postgres")
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError("Postgres mode requires psycopg. Run: pip install 'psycopg[binary]'") from exc
        return psycopg.connect(DATABASE_URL, row_factory=dict_row)

    path = Path(sqlite_path)
    if path.parent != Path("."):
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def ensure_schemas(conn) -> None:
    if not is_postgres():
        return
    conn.execute(f"CREATE SCHEMA IF NOT EXISTS {_quote_ident(system_schema())}")
    conn.execute(f"CREATE SCHEMA IF NOT EXISTS {_quote_ident(user_schema())}")


def execute(conn, sql: str, params: Sequence[Any] | None = None):
    return conn.execute(adapt_sql(sql), params or ())


def executemany(conn, sql: str, params: Iterable[Sequence[Any] | dict[str, Any]]):
    if is_postgres():
        with conn.cursor() as cur:
            return cur.executemany(adapt_sql(sql), params)
    return conn.executemany(adapt_sql(sql), params)


def read_dataframe(conn, sql: str, params: Sequence[Any] | None = None) -> pd.DataFrame:
    if is_postgres():
        cur = execute(conn, sql, params)
        rows = cur.fetchall()
        if rows:
            return pd.DataFrame(rows)
        columns = [desc.name if hasattr(desc, "name") else desc[0] for desc in (cur.description or [])]
        return pd.DataFrame(columns=columns)
    return pd.read_sql(sql, conn, params=params or ())


def bulk_insert_dataframe(conn, table: str, df: pd.DataFrame, columns: list[str]) -> None:
    if df.empty:
        return
    if is_postgres():
        column_sql = ", ".join(_quote_ident(col) for col in columns)
        with conn.cursor() as cur:
            with cur.copy(f"COPY {table} ({column_sql}) FROM STDIN") as copy:
                for row in df[columns].itertuples(index=False, name=None):
                    copy.write_row(row)
        return

    df[columns].to_sql(table, conn, if_exists="append", index=False, method="multi")


def integrity_error_types() -> tuple[type[BaseException], ...]:
    errors: list[type[BaseException]] = [sqlite3.IntegrityError]
    if is_postgres():
        try:
            import psycopg

            errors.append(psycopg.IntegrityError)
        except ImportError:
            pass
    return tuple(errors)
