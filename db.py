from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, Any
import contextlib


@dataclass
class ConnectionConfig:
    name: str
    db_type: str
    host: str
    port: int
    database: str
    username: str
    password: str
    driver: Optional[str] = None


# ── Driver abstraction ─────────────────────────────────────────────────────

class _BaseDriver:
    def __init__(self, cfg: ConnectionConfig):
        self.cfg = cfg

    def connection(self):
        raise NotImplementedError

    def test(self):
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")


class PostgresDriver(_BaseDriver):
    def connection(self):
        import psycopg2
        return psycopg2.connect(
            host=self.cfg.host,
            port=self.cfg.port,
            dbname=self.cfg.database,
            user=self.cfg.username,
            password=self.cfg.password,
        )


class SqlServerDriver(_BaseDriver):
    def connection(self):
        import pyodbc
        driver = self.cfg.driver or "ODBC Driver 17 for SQL Server"
        conn_str = (
            f"DRIVER={{{driver}}};"
            f"SERVER={self.cfg.host},{self.cfg.port};"
            f"DATABASE={self.cfg.database};"
            f"UID={self.cfg.username};"
            f"PWD={self.cfg.password};"
        )
        return pyodbc.connect(conn_str)

    def test(self):
        with self.connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT 1")
            cur.close()


def get_driver(cfg: ConnectionConfig) -> _BaseDriver:
    if cfg.db_type == "postgres":
        return PostgresDriver(cfg)
    elif cfg.db_type == "sqlserver":
        return SqlServerDriver(cfg)
    raise ValueError(f"Unsupported db_type: {cfg.db_type}")


# ── Helpers ────────────────────────────────────────────────────────────────

def _exec_postgres(cfg, query, params=None, fetch=True):
    drv = PostgresDriver(cfg)
    with drv.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params or [])
            if fetch:
                cols = [d[0] for d in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()]
            conn.commit()


def _exec_sqlserver(cfg, query, params=None, fetch=True):
    drv = SqlServerDriver(cfg)
    with drv.connection() as conn:
        cur = conn.cursor()
        cur.execute(query, params or [])
        if fetch:
            cols = [d[0] for d in cur.description]
            result = [dict(zip(cols, row)) for row in cur.fetchall()]
            cur.close()
            return result
        conn.commit()
        cur.close()


def _exec(cfg: ConnectionConfig, query, params=None, fetch=True):
    if cfg.db_type == "postgres":
        return _exec_postgres(cfg, query, params, fetch)
    return _exec_sqlserver(cfg, query, params, fetch)


# ── Public API ─────────────────────────────────────────────────────────────

def list_tables(cfg: ConnectionConfig, schema: str) -> list[str]:
    if cfg.db_type == "postgres":
        rows = _exec(cfg,
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = %s AND table_type = 'BASE TABLE' ORDER BY table_name",
            [schema])
    else:
        rows = _exec(cfg,
            "SELECT TABLE_NAME as table_name FROM INFORMATION_SCHEMA.TABLES "
            "WHERE TABLE_SCHEMA = ? AND TABLE_TYPE = 'BASE TABLE' ORDER BY TABLE_NAME",
            [schema])
    return [r["table_name"] for r in rows]


def list_columns(cfg: ConnectionConfig, schema: str, table: str) -> list[dict]:
    if cfg.db_type == "postgres":
        rows = _exec(cfg,
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position",
            [schema, table])
    else:
        rows = _exec(cfg,
            "SELECT COLUMN_NAME as column_name, DATA_TYPE as data_type "
            "FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ? ORDER BY ORDINAL_POSITION",
            [schema, table])
    return rows


def _quoted(cfg: ConnectionConfig, identifier: str) -> str:
    if cfg.db_type == "postgres":
        return f'"{identifier}"'
    return f"[{identifier}]"


def preview_changes(
    cfg: ConnectionConfig,
    schema: str,
    table: str,
    column: str,
    mappings: list[dict],
) -> dict:
    if not mappings:
        return {"rows": [], "total_affected": 0}

    from_values = [m["from"] for m in mappings]
    q_table = f"{_quoted(cfg, schema)}.{_quoted(cfg, table)}"
    q_col = _quoted(cfg, column)
    ph = "%s" if cfg.db_type == "postgres" else "?"

    placeholders = ", ".join([ph] * len(from_values))
    query = f"SELECT {q_col} as current_value, COUNT(*) as row_count FROM {q_table} WHERE {q_col} IN ({placeholders}) GROUP BY {q_col}"
    rows = _exec(cfg, query, from_values)

    mapping_index = {m["from"]: m["to"] for m in mappings}
    preview_rows = [
        {
            "current_value": str(r["current_value"]),
            "new_value": mapping_index.get(str(r["current_value"]), ""),
            "row_count": r["row_count"],
        }
        for r in rows
    ]
    total = sum(r["row_count"] for r in preview_rows)
    return {"rows": preview_rows, "total_affected": total}


def apply_changes(
    cfg: ConnectionConfig,
    schema: str,
    table: str,
    column: str,
    mappings: list[dict],
) -> dict:
    if not mappings:
        return {"updated": 0}

    q_table = f"{_quoted(cfg, schema)}.{_quoted(cfg, table)}"
    q_col = _quoted(cfg, column)
    ph = "%s" if cfg.db_type == "postgres" else "?"

    drv = get_driver(cfg)
    total_updated = 0

    if cfg.db_type == "postgres":
        with drv.connection() as conn:
            with conn.cursor() as cur:
                for m in mappings:
                    cur.execute(
                        f"UPDATE {q_table} SET {q_col} = {ph} WHERE {q_col} = {ph}",
                        [m["to"], m["from"]],
                    )
                    total_updated += cur.rowcount
            conn.commit()
    else:
        with drv.connection() as conn:
            cur = conn.cursor()
            for m in mappings:
                cur.execute(
                    f"UPDATE {q_table} SET {q_col} = {ph} WHERE {q_col} = {ph}",
                    [m["to"], m["from"]],
                )
                total_updated += cur.rowcount
            conn.commit()
            cur.close()

    return {"updated": total_updated}
