from datetime import date

import pytest

from finanzas_agent import db

MES = date.today().strftime("%Y-%m")


@pytest.fixture
def conn(tmp_path):
    with db.sesion(tmp_path / "t.db") as c:
        yield c


def test_registrar_normaliza_categoria_y_fecha(conn):
    g = db.registrar_gasto(conn, 10.556, "  Comida ", "pan")
    assert g["categoria"] == "comida"
    assert g["monto"] == 10.56
    assert g["fecha"] == date.today().isoformat()


@pytest.mark.parametrize("monto", [0, -5])
def test_registrar_rechaza_monto_no_positivo(conn, monto):
    with pytest.raises(ValueError):
        db.registrar_gasto(conn, monto, "comida")


def test_registrar_rechaza_fecha_invalida(conn):
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        db.registrar_gasto(conn, 5, "comida", fecha="02/10/2026")


def test_resumen_por_categoria(conn):
    db.registrar_gasto(conn, 100, "comida", fecha=f"{MES}-01")
    db.registrar_gasto(conn, 50, "comida", fecha=f"{MES}-02")
    db.registrar_gasto(conn, 30, "ocio", fecha=f"{MES}-02")
    db.registrar_gasto(conn, 999, "comida", fecha="2000-01-01")  # otro mes
    assert db.resumen_por_categoria(conn, MES) == [
        {"categoria": "comida", "total": 150.0, "n": 2},
        {"categoria": "ocio", "total": 30.0, "n": 1},
    ]


def test_estado_presupuestos_detecta_exceso(conn):
    db.definir_presupuesto(conn, "ocio", 100)
    db.definir_presupuesto(conn, "hogar", 500)
    db.registrar_gasto(conn, 125, "ocio", fecha=f"{MES}-05")
    estado = {e["categoria"]: e for e in db.estado_presupuestos(conn, MES)}
    assert estado["ocio"]["excedido"] is True
    assert estado["ocio"]["restante"] == -25.0
    assert estado["hogar"]["gastado"] == 0
    assert estado["hogar"]["excedido"] is False


def test_definir_presupuesto_actualiza(conn):
    db.definir_presupuesto(conn, "ocio", 100)
    db.definir_presupuesto(conn, "ocio", 200)
    assert db.estado_presupuestos(conn, MES)[0]["limite"] == 200


def test_eliminar_gasto(conn):
    g = db.registrar_gasto(conn, 10, "comida")
    assert db.eliminar_gasto(conn, g["id"]) is True
    assert db.eliminar_gasto(conn, g["id"]) is False
