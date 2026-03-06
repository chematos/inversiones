#!/usr/bin/env python3
"""
MCP Server: Inversiones Montevideo
Expone los datos de apartments.json como herramientas para Claude.

Uso con Claude Desktop:
  Ver mcp_server/README_MCP.md para la configuracion.
"""

import json
import re
from pathlib import Path
from mcp.server.fastmcp import FastMCP

DATA_PATH = Path(__file__).parent.parent / "data" / "apartments.json"

mcp = FastMCP("Inversiones MVD")


# ─── Helpers ─────────────────────────────────────────────────────────────────

def load_data() -> dict:
    """Carga el JSON de datos. Lanza FileNotFoundError si no existe."""
    if not DATA_PATH.exists():
        raise FileNotFoundError(
            "No se encontro data/apartments.json. "
            "Ejecuta el scraper primero: python scraper/scraper.py --test"
        )
    with open(DATA_PATH, encoding="utf-8") as f:
        return json.load(f)


def normalize(text: str) -> str:
    return (
        str(text).lower().strip()
        .replace("á", "a").replace("é", "e").replace("í", "i")
        .replace("ó", "o").replace("ú", "u").replace("ñ", "n")
    )


def apt_summary(apt: dict) -> dict:
    """Version resumida de un apartamento para listados."""
    return {
        "id":               apt.get("id"),
        "titulo":           apt.get("title"),
        "zona":             apt.get("zone"),
        "precio_usd":       apt.get("price_usd"),
        "m2":               apt.get("m2"),
        "precio_por_m2":    apt.get("price_per_m2"),
        "habitaciones":     apt.get("rooms"),
        "rentabilidad_pct": apt.get("rentability_pct"),
        "score":            apt.get("score"),
        "alquiler_est_uyu": apt.get("estimated_rent_uyu"),
        "gastos_com_uyu":   apt.get("gastos_comunes_uyu"),
        "dias_publicado":   apt.get("days_on_market"),
        "url":              apt.get("url"),
    }


# ─── Herramientas MCP ─────────────────────────────────────────────────────────

@mcp.tool()
def listar_apartamentos(
    zona: str | None = None,
    precio_max_usd: int | None = None,
    precio_min_usd: int | None = None,
    score_minimo: int | None = None,
    rentabilidad_minima: float | None = None,
    gastos_comunes_max_uyu: int | None = None,
    ordenar_por: str = "score",
    limite: int = 15,
) -> str:
    """
    Lista apartamentos con filtros opcionales.

    Parametros:
    - zona: filtrar por zona (ej: "buceo", "malvin"). Busqueda parcial, ignora acentos.
    - precio_max_usd: precio maximo en USD.
    - precio_min_usd: precio minimo en USD.
    - score_minimo: puntaje minimo de inversion (0-100). 10% rentabilidad = 100.
    - rentabilidad_minima: rentabilidad bruta anual minima en % (ej: 6.5 para 6.5%).
    - gastos_comunes_max_uyu: maximo de gastos comunes mensuales en UYU.
    - ordenar_por: "score" | "rentabilidad" | "precio_asc" | "precio_desc" | "m2" | "dias".
    - limite: cantidad maxima de resultados (default 15).
    """
    data = load_data()
    apts = data["apartments"]

    # Filtros
    if zona:
        norm_zona = normalize(zona)
        apts = [a for a in apts if norm_zona in normalize(a.get("zone", ""))]

    if precio_max_usd is not None:
        apts = [a for a in apts if (a.get("price_usd") or 0) <= precio_max_usd]

    if precio_min_usd is not None:
        apts = [a for a in apts if (a.get("price_usd") or 0) >= precio_min_usd]

    if score_minimo is not None:
        apts = [a for a in apts if (a.get("score") or 0) >= score_minimo]

    if rentabilidad_minima is not None:
        apts = [a for a in apts if (a.get("rentability_pct") or 0) >= rentabilidad_minima]

    if gastos_comunes_max_uyu is not None:
        apts = [
            a for a in apts
            if a.get("gastos_comunes_uyu") is None
            or a["gastos_comunes_uyu"] <= gastos_comunes_max_uyu
        ]

    # Ordenamiento
    sort_key = {
        "score":        lambda x: -(x.get("score") or 0),
        "rentabilidad": lambda x: -(x.get("rentability_pct") or 0),
        "precio_asc":   lambda x:  (x.get("price_usd") or 0),
        "precio_desc":  lambda x: -(x.get("price_usd") or 0),
        "m2":           lambda x:  (x.get("price_per_m2") or 999999),
        "dias":         lambda x: -(x.get("days_on_market") or 0),
    }.get(ordenar_por, lambda x: -(x.get("score") or 0))

    apts = sorted(apts, key=sort_key)[:limite]

    resultado = {
        "total_encontrados": len(apts),
        "total_en_dataset":  data.get("total", 0),
        "ultima_actualizacion": data.get("last_updated"),
        "apartamentos": [apt_summary(a) for a in apts],
    }
    return json.dumps(resultado, ensure_ascii=False, indent=2)


@mcp.tool()
def obtener_apartamento(id_o_url: str) -> str:
    """
    Devuelve todos los datos de un apartamento especifico.

    Parametros:
    - id_o_url: el ID del apartamento (ej: "MLU-123456") o cualquier fragmento
                de la URL o titulo para buscarlo.
    """
    data = load_data()
    query = normalize(id_o_url)

    for apt in data["apartments"]:
        if (
            query in normalize(apt.get("id", ""))
            or query in normalize(apt.get("url", ""))
            or query in normalize(apt.get("title", ""))
        ):
            return json.dumps(apt, ensure_ascii=False, indent=2)

    return json.dumps({"error": f"No se encontro apartamento con '{id_o_url}'"})


@mcp.tool()
def resumen_mercado() -> str:
    """
    Devuelve estadisticas generales del mercado actual:
    cantidad de apartamentos, promedios de precio, rentabilidad, score,
    distribucion por zona, y los 3 mejores por score.
    """
    data = load_data()
    apts = data["apartments"]

    if not apts:
        return json.dumps({"error": "No hay datos disponibles."})

    precios = [a["price_usd"] for a in apts if a.get("price_usd")]
    rents   = [a["rentability_pct"] for a in apts if a.get("rentability_pct")]
    scores  = [a["score"] for a in apts if a.get("score") is not None]
    m2s     = [a["price_per_m2"] for a in apts if a.get("price_per_m2")]
    ggcc    = [a["gastos_comunes_uyu"] for a in apts if a.get("gastos_comunes_uyu")]

    # Distribucion por zona
    zonas: dict[str, int] = {}
    for a in apts:
        z = a.get("zone", "Desconocida")
        zonas[z] = zonas.get(z, 0) + 1

    # Top 3 por score
    top3 = sorted(apts, key=lambda x: x.get("score", 0), reverse=True)[:3]

    resultado = {
        "ultima_actualizacion": data.get("last_updated"),
        "tc_usd_uyu":           data.get("tc_usd_uyu"),
        "total_apartamentos":   len(apts),
        "precios_usd": {
            "minimo":   min(precios),
            "maximo":   max(precios),
            "promedio": round(sum(precios) / len(precios)),
        },
        "rentabilidad_pct": {
            "minima":   min(rents),
            "maxima":   max(rents),
            "promedio": round(sum(rents) / len(rents), 2),
        },
        "score": {
            "minimo":   min(scores),
            "maximo":   max(scores),
            "promedio": round(sum(scores) / len(scores)),
        },
        "precio_por_m2_usd": {
            "minimo":   min(m2s),
            "maximo":   max(m2s),
            "promedio": round(sum(m2s) / len(m2s)),
        },
        "gastos_comunes_uyu": {
            "con_dato":    len(ggcc),
            "sin_dato":    len(apts) - len(ggcc),
            "promedio":    round(sum(ggcc) / len(ggcc)) if ggcc else None,
        },
        "por_zona": zonas,
        "top_3_por_score": [apt_summary(a) for a in top3],
    }
    return json.dumps(resultado, ensure_ascii=False, indent=2)


@mcp.tool()
def comparar_apartamentos(ids: list[str]) -> str:
    """
    Compara varios apartamentos lado a lado.

    Parametros:
    - ids: lista de IDs o fragmentos de URL/titulo (ej: ["MLU-123", "MLU-456"]).
           Minimo 2, maximo 5.
    """
    if len(ids) < 2:
        return json.dumps({"error": "Se necesitan al menos 2 IDs para comparar."})
    if len(ids) > 5:
        return json.dumps({"error": "Maximo 5 apartamentos para comparar."})

    data = load_data()
    encontrados = []

    for query_raw in ids:
        query = normalize(query_raw)
        for apt in data["apartments"]:
            if (
                query in normalize(apt.get("id", ""))
                or query in normalize(apt.get("url", ""))
                or query in normalize(apt.get("title", ""))
            ):
                encontrados.append(apt_summary(apt))
                break
        else:
            encontrados.append({"error": f"No encontrado: {query_raw}"})

    return json.dumps({"comparacion": encontrados}, ensure_ascii=False, indent=2)


# ─── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run()
