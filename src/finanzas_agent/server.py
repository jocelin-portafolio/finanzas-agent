"""Servidor MCP de finanzas personales.

Se puede usar con cualquier cliente MCP (Claude Desktop, Claude Code, el agente de
este repo). Transporte por defecto: stdio.

    python -m finanzas_agent.server
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from finanzas_agent import db

mcp = MCPServer("finanzas")


@contextmanager
def _validacion() -> Iterator[None]:
    """Convierte errores de validación en ToolError para que el mensaje llegue al modelo.

    MCP 2.x oculta el texto de cualquier otra excepción (la trata como crash).
    """
    try:
        yield
    except ValueError as e:
        raise ToolError(str(e)) from e

Fecha = Annotated[str | None, Field(description="Fecha ISO YYYY-MM-DD. Si se omite, hoy.")]
Mes = Annotated[str | None, Field(description="Mes YYYY-MM. Si se omite, el mes actual.")]
Categoria = Annotated[
    str,
    Field(description="Categoría en minúsculas, p. ej. 'comida', 'transporte', 'ocio', 'hogar'."),
]


@mcp.tool()
def registrar_gasto(
    monto: Annotated[float, Field(gt=0, description="Monto positivo en la moneda del usuario.")],
    categoria: Categoria,
    descripcion: Annotated[str, Field(description="Descripción breve del gasto.")] = "",
    fecha: Fecha = None,
) -> dict:
    """Registra un gasto nuevo. Devuelve el gasto guardado con su id."""
    with _validacion(), db.sesion() as conn:
        return db.registrar_gasto(conn, monto, categoria, descripcion, fecha)


@mcp.tool()
def listar_gastos(
    desde: Fecha = None,
    hasta: Fecha = None,
    categoria: Annotated[str | None, Field(description="Filtrar por categoría.")] = None,
    limite: Annotated[int, Field(ge=1, le=500, description="Máximo de resultados.")] = 50,
) -> dict:
    """Lista gastos (más recientes primero), con filtros opcionales por rango y categoría.

    Úsala para buscar el id de un gasto antes de eliminarlo.
    """
    with _validacion(), db.sesion() as conn:
        gastos = db.listar_gastos(conn, desde, hasta, categoria, limite)
    return {"gastos": gastos, "cantidad": len(gastos)}


@mcp.tool()
def resumen_por_categoria(mes: Mes = None) -> dict:
    """Total gastado por categoría en un mes, ordenado de mayor a menor."""
    with _validacion(), db.sesion() as conn:
        filas = db.resumen_por_categoria(conn, mes)
    return {"mes": mes, "categorias": filas, "total": round(sum(f["total"] for f in filas), 2)}


@mcp.tool()
def definir_presupuesto(
    categoria: Categoria,
    limite_mensual: Annotated[float, Field(gt=0, description="Límite mensual para la categoría.")],
) -> dict:
    """Crea o actualiza el presupuesto mensual de una categoría."""
    with _validacion(), db.sesion() as conn:
        return db.definir_presupuesto(conn, categoria, limite_mensual)


@mcp.tool()
def estado_presupuestos(mes: Mes = None) -> dict:
    """Compara lo gastado contra el presupuesto de cada categoría en un mes."""
    with _validacion(), db.sesion() as conn:
        return {"mes": mes, "presupuestos": db.estado_presupuestos(conn, mes)}


@mcp.tool(annotations=ToolAnnotations(destructive_hint=True))
def eliminar_gasto(
    gasto_id: Annotated[int, Field(description="id del gasto (obtenlo con listar_gastos).")],
) -> dict:
    """Elimina un gasto de forma permanente. Requiere confirmación del usuario."""
    with _validacion(), db.sesion() as conn:
        if not db.eliminar_gasto(conn, gasto_id):
            raise ValueError(f"No existe un gasto con id {gasto_id}.")
    return {"eliminado": gasto_id}


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
