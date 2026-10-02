"""Chat interactivo en terminal: `python -m finanzas_agent.cli`."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from dotenv import load_dotenv

from finanzas_agent.agent import AgenteFinanzas


def confirmar_en_terminal(nombre: str, entrada: dict) -> bool:
    print(f"\n⚠  El agente quiere ejecutar {nombre}({json.dumps(entrada, ensure_ascii=False)})")
    return input("   ¿Aprobar? [s/N] ").strip().lower() in {"s", "si", "sí", "y"}


async def _chat() -> None:
    async with AgenteFinanzas.conectar(
        confirmar=confirmar_en_terminal, trace_dir=Path("traces")
    ) as agente:
        print("Asistente de finanzas. Escribe 'salir' para terminar.\n")
        while True:
            try:
                texto = input("tú › ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not texto:
                continue
            if texto.lower() in {"salir", "exit", "quit"}:
                break
            r = await agente.preguntar(texto)
            herramientas = ", ".join(c.nombre for c in r.llamadas) or "ninguna"
            print(f"\nagente › {r.respuesta}")
            print(f"  [{r.pasos} pasos · herramientas: {herramientas} · "
                  f"{r.latencia_s:.1f}s · ${r.costo_usd:.4f}]\n")


def main() -> None:
    load_dotenv()
    asyncio.run(_chat())


if __name__ == "__main__":
    main()
