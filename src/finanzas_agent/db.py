"""Capa de datos (SQLite). Sin dependencias de MCP ni del LLM: se testea aislada."""

from __future__ import annotations

import os
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS gastos (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha       TEXT    NOT NULL,           -- ISO YYYY-MM-DD
    monto       REAL    NOT NULL CHECK (monto > 0),
    categoria   TEXT    NOT NULL,
    descripcion TEXT    NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_gastos_fecha ON gastos (fecha);

CREATE TABLE IF NOT EXISTS presupuestos (
    categoria      TEXT PRIMARY KEY,
    limite_mensual REAL NOT NULL CHECK (limite_mensual > 0)
);
"""

_MES_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def db_path() -> Path:
    return Path(os.environ.get("FINANZAS_DB", "data/finanzas.db"))


@contextmanager
def sesion(path: str | Path | None = None) -> Iterator[sqlite3.Connection]:
    """Abre una conexión, aplica el esquema, hace commit al salir y cierra."""
    p = Path(path) if path else db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


# --- validación -------------------------------------------------------------

def _categoria(valor: str) -> str:
    c = valor.strip().lower()
    if not c:
        raise ValueError("La categoría no puede estar vacía.")
    return c


def _fecha(valor: str | None) -> str:
    if valor is None:
        return date.today().isoformat()
    try:
        return date.fromisoformat(valor).isoformat()
    except ValueError as e:
        raise ValueError(f"Fecha inválida '{valor}'. Usa el formato YYYY-MM-DD.") from e


def _mes(valor: str | None) -> str:
    m = valor or date.today().strftime("%Y-%m")
    if not _MES_RE.match(m):
        raise ValueError(f"Mes inválido '{m}'. Usa el formato YYYY-MM.")
    return m


# --- operaciones ------------------------------------------------------------

def registrar_gasto(
    conn: sqlite3.Connection,
    monto: float,
    categoria: str,
    descripcion: str = "",
    fecha: str | None = None,
) -> dict:
    if monto <= 0:
        raise ValueError("El monto debe ser mayor que 0.")
    fila = (_fecha(fecha), round(monto, 2), _categoria(categoria), descripcion.strip())
    cur = conn.execute(
        "INSERT INTO gastos (fecha, monto, categoria, descripcion) VALUES (?, ?, ?, ?)", fila
    )
    return {"id": cur.lastrowid, "fecha": fila[0], "monto": fila[1],
            "categoria": fila[2], "descripcion": fila[3]}


def listar_gastos(
    conn: sqlite3.Connection,
    desde: str | None = None,
    hasta: str | None = None,
    categoria: str | None = None,
    limite: int = 50,
) -> list[dict]:
    sql, params = "SELECT * FROM gastos WHERE 1=1", []
    if desde:
        sql += " AND fecha >= ?"
        params.append(_fecha(desde))
    if hasta:
        sql += " AND fecha <= ?"
        params.append(_fecha(hasta))
    if categoria:
        sql += " AND categoria = ?"
        params.append(_categoria(categoria))
    sql += " ORDER BY fecha DESC, id DESC LIMIT ?"
    params.append(max(1, min(limite, 500)))
    return [dict(r) for r in conn.execute(sql, params)]


def resumen_por_categoria(conn: sqlite3.Connection, mes: str | None = None) -> list[dict]:
    m = _mes(mes)
    filas = conn.execute(
        """SELECT categoria, ROUND(SUM(monto), 2) AS total, COUNT(*) AS n
           FROM gastos WHERE substr(fecha, 1, 7) = ?
           GROUP BY categoria ORDER BY total DESC""",
        (m,),
    )
    return [dict(r) for r in filas]


def definir_presupuesto(conn: sqlite3.Connection, categoria: str, limite_mensual: float) -> dict:
    if limite_mensual <= 0:
        raise ValueError("El límite mensual debe ser mayor que 0.")
    c = _categoria(categoria)
    conn.execute(
        """INSERT INTO presupuestos (categoria, limite_mensual) VALUES (?, ?)
           ON CONFLICT(categoria) DO UPDATE SET limite_mensual = excluded.limite_mensual""",
        (c, round(limite_mensual, 2)),
    )
    return {"categoria": c, "limite_mensual": round(limite_mensual, 2)}


def estado_presupuestos(conn: sqlite3.Connection, mes: str | None = None) -> list[dict]:
    m = _mes(mes)
    filas = conn.execute(
        """SELECT p.categoria, p.limite_mensual AS limite,
                  ROUND(COALESCE(SUM(g.monto), 0), 2) AS gastado
           FROM presupuestos p
           LEFT JOIN gastos g ON g.categoria = p.categoria AND substr(g.fecha, 1, 7) = ?
           GROUP BY p.categoria ORDER BY p.categoria""",
        (m,),
    )
    out = []
    for r in filas:
        d = dict(r)
        d["restante"] = round(d["limite"] - d["gastado"], 2)
        d["porcentaje"] = round(100 * d["gastado"] / d["limite"], 1)
        d["excedido"] = d["gastado"] > d["limite"]
        out.append(d)
    return out


def eliminar_gasto(conn: sqlite3.Connection, gasto_id: int) -> bool:
    return conn.execute("DELETE FROM gastos WHERE id = ?", (gasto_id,)).rowcount > 0
