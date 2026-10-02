"""Ejecuta los casos de evals/casos.yaml contra el agente real y reporta métricas.

    python evals/run_evals.py                 # todos los casos
    python evals/run_evals.py -k presupuesto  # filtra por id
    python evals/run_evals.py --repeticiones 3

Cada ejecución llama a la API de Claude y cuesta dinero: revisa el costo estimado
que imprime al final.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml
from dotenv import load_dotenv

from finanzas_agent import db
from finanzas_agent.agent import MODEL, AgenteFinanzas, Resultado

RAIZ = Path(__file__).parent


@dataclass
class Evaluacion:
    caso: str
    ok: bool
    fallos: list[str]
    resultado: Resultado


def _formatear(valor, ctx: dict):
    if isinstance(valor, str):
        return valor.format(**ctx)
    if isinstance(valor, dict):
        return {k: _formatear(v, ctx) for k, v in valor.items()}
    return valor


def _sembrar(path: Path, semilla: dict, ctx: dict) -> None:
    with db.sesion(path) as conn:
        for p in semilla.get("presupuestos", []):
            db.definir_presupuesto(conn, **_formatear(p, ctx))
        for g in semilla.get("gastos", []):
            db.registrar_gasto(conn, **_formatear(g, ctx))


def _verificar(caso: dict, r: Resultado, path: Path) -> list[str]:
    v, fallos = caso.get("verificar", {}), []
    exitosas = {c.nombre for c in r.llamadas if not c.es_error}
    llamadas = {c.nombre for c in r.llamadas}

    for h in v.get("herramientas", []):
        if h not in llamadas:
            fallos.append(f"no llamó a {h}")
    for h in v.get("no_herramientas", []):
        if h in exitosas:
            fallos.append(f"ejecutó {h} y no debía")

    # Normaliza "1.234,50" / "1,234.50" → comparación tolerante a separadores
    texto = r.respuesta.lower().replace(",", ".")
    for s in v.get("respuesta_contiene", []):
        if s.lower().replace(",", ".") not in texto:
            fallos.append(f"respuesta sin '{s}'")

    if sql := v.get("sql"):
        with db.sesion(path) as conn:
            valor = conn.execute(sql["consulta"]).fetchone()[0]
        if valor != sql["esperado"]:
            fallos.append(f"sql: {valor!r} != {sql['esperado']!r}")

    if (tope := v.get("max_pasos")) and r.pasos > tope:
        fallos.append(f"{r.pasos} pasos > {tope}")
    if r.stop_reason in {"refusal", "max_pasos"}:
        fallos.append(f"stop_reason={r.stop_reason}")
    return fallos


async def evaluar(caso: dict) -> Evaluacion:
    ctx = {"hoy": date.today().isoformat(), "mes": date.today().strftime("%Y-%m")}
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "eval.db"
        _sembrar(path, caso.get("semilla", {}), ctx)
        # El harness rechaza toda confirmación humana: las acciones destructivas no ocurren.
        async with AgenteFinanzas.conectar(db_path=path, confirmar=lambda *_: False) as agente:
            r = await agente.preguntar(caso["prompt"])
        fallos = _verificar(caso, r, path)
    return Evaluacion(caso["id"], not fallos, fallos, r)


def _percentil(xs: list[float], p: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p * (len(xs) - 1))))]


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-k", help="filtra casos cuyo id contenga este texto")
    ap.add_argument("--repeticiones", type=int, default=1)
    ap.add_argument("--concurrencia", type=int, default=3)
    args = ap.parse_args()

    casos = yaml.safe_load((RAIZ / "casos.yaml").read_text(encoding="utf-8"))
    if args.k:
        casos = [c for c in casos if args.k in c["id"]]
    casos = casos * args.repeticiones

    sem = asyncio.Semaphore(args.concurrencia)

    async def limitado(c):
        async with sem:
            return await evaluar(c)

    evals = await asyncio.gather(*(limitado(c) for c in casos))

    print(f"\nModelo: {MODEL}\n")
    print(f"{'caso':<34} {'ok':<4} {'pasos':>5} {'seg':>6} {'USD':>8}  fallos")
    print("-" * 90)
    for e in evals:
        r = e.resultado
        print(f"{e.caso:<34} {'✔' if e.ok else '✘':<4} {r.pasos:>5} {r.latencia_s:>6.1f} "
              f"{r.costo_usd:>8.4f}  {'; '.join(e.fallos)}")

    lat = [e.resultado.latencia_s for e in evals]
    costo = sum(e.resultado.costo_usd for e in evals)
    exito = sum(e.ok for e in evals) / len(evals)
    resumen = {
        "modelo": MODEL,
        "casos": len(evals),
        "tasa_exito": round(exito, 3),
        "latencia_p50_s": round(statistics.median(lat), 2),
        "latencia_p95_s": round(_percentil(lat, 0.95), 2),
        "costo_total_usd": round(costo, 4),
        "costo_medio_usd": round(costo / len(evals), 4),
    }
    print("-" * 90)
    print(json.dumps(resumen, indent=2, ensure_ascii=False))

    salida = RAIZ / "resultados"
    salida.mkdir(exist_ok=True)
    (salida / "ultimo.json").write_text(
        json.dumps({"resumen": resumen,
                    "casos": [{"id": e.caso, "ok": e.ok, "fallos": e.fallos,
                               "pasos": e.resultado.pasos,
                               "herramientas": [c.nombre for c in e.resultado.llamadas],
                               "respuesta": e.resultado.respuesta} for e in evals]},
                   indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return 0 if exito == 1 else 1


if __name__ == "__main__":
    load_dotenv()
    sys.exit(asyncio.run(main()))
