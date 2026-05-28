from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional
import json

from db import get_driver, ConnectionConfig, list_tables, list_columns, preview_changes, apply_changes

app = FastAPI(title="IDChanger")
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def index():
    return FileResponse("static/index.html")


# ── Connection management (in-memory for session) ──────────────────────────
_connections: dict[str, dict] = {}


class ConnectRequest(BaseModel):
    name: str
    db_type: str          # "postgres" | "sqlserver"
    host: str
    port: int
    database: str
    username: str
    password: str
    # SQL Server only
    driver: Optional[str] = None


@app.post("/api/connections")
def add_connection(req: ConnectRequest):
    cfg = ConnectionConfig(**req.model_dump())
    try:
        driver = get_driver(cfg)
        driver.test()
    except Exception as e:
        raise HTTPException(400, str(e))
    _connections[req.name] = req.model_dump()
    return {"ok": True}


@app.get("/api/connections")
def get_connections():
    return list(_connections.keys())


@app.delete("/api/connections/{name}")
def delete_connection(name: str):
    _connections.pop(name, None)
    return {"ok": True}


@app.get("/api/connections/{name}/tables")
def get_tables(name: str, schema: str = "public"):
    cfg = _get_cfg(name)
    return list_tables(cfg, schema)


@app.get("/api/connections/{name}/tables/{table}/columns")
def get_columns(name: str, table: str, schema: str = "public"):
    cfg = _get_cfg(name)
    return list_columns(cfg, schema, table)


class PreviewRequest(BaseModel):
    connection: str
    schema: str
    table: str
    column: str
    mappings: list[dict]   # [{"from": "...", "to": "..."}]


@app.post("/api/preview")
def preview(req: PreviewRequest):
    cfg = _get_cfg(req.connection)
    return preview_changes(cfg, req.schema, req.table, req.column, req.mappings)


class ApplyRequest(BaseModel):
    connection: str
    schema: str
    table: str
    column: str
    mappings: list[dict]


@app.post("/api/apply")
def apply(req: ApplyRequest):
    cfg = _get_cfg(req.connection)
    return apply_changes(cfg, req.schema, req.table, req.column, req.mappings)


def _get_cfg(name: str) -> "ConnectionConfig":
    if name not in _connections:
        raise HTTPException(404, f"Connection '{name}' not found")
    return ConnectionConfig(**_connections[name])
