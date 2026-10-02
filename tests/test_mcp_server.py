"""Prueba de integración del servidor MCP por stdio. No llama a la API de Claude."""

import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def _texto(resultado) -> str:
    return "\n".join(c.text for c in resultado.content if c.type == "text")


async def test_servidor_expone_herramientas_y_responde(tmp_path):
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "finanzas_agent.server"],
        env={**os.environ, "FINANZAS_DB": str(tmp_path / "mcp.db")},
    )
    async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
        await s.initialize()

        nombres = {t.name for t in (await s.list_tools()).tools}
        assert nombres == {
            "registrar_gasto", "listar_gastos", "resumen_por_categoria",
            "definir_presupuesto", "estado_presupuestos", "eliminar_gasto",
        }

        res = await s.call_tool("registrar_gasto", {"monto": 42, "categoria": "Ocio"})
        assert not res.is_error
        assert json.loads(_texto(res))["categoria"] == "ocio"

        listado = json.loads(_texto(await s.call_tool("listar_gastos", {})))
        assert listado["cantidad"] == 1

        # Los errores de validación llegan al cliente como is_error, no como excepción
        malo = await s.call_tool("eliminar_gasto", {"gasto_id": 12345})
        assert malo.is_error
        assert "No existe" in _texto(malo)
