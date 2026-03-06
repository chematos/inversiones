#!/usr/bin/env python3
"""
Scraper híbrido de apartamentos en Montevideo para inversión inmobiliaria.

  Búsqueda : MercadoLibre API REST  (sin browser, rápido)
  Detalles : Playwright async       (gastos comunes, días en mercado)

Uso:
  python scraper.py          # scrape completo
  python scraper.py --test   # primeros 10 listados, 3 detalles

Variables de entorno requeridas:
  ML_CLIENT_ID
  ML_CLIENT_SECRET
"""

import asyncio
import json
import os
import re
import logging
import sys
import random
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, BrowserContext

# ─── Configuración ────────────────────────────────────────────────────────────

MIN_PRICE_USD = 60_000
MAX_PRICE_USD = 98_000
CONCURRENCY   = 6       # páginas de detalle en paralelo

# Zonas permitidas (claves normalizadas sin tildes)
ALLOWED_ZONES = {"buceo", "malvin", "cordon", "carrasco"}

# Alquiler mensual estimado en UYU — 1 dormitorio / monoambiente (2025-2026)
ZONE_RENT_UYU = {
    "carrasco": 38_000,
    "buceo":    25_000,
    "malvin":   23_000,
    "cordon":   21_000,
}
DEFAULT_RENT_UYU = 23_000

# MercadoLibre API
ML_SITE     = "MLU"
ML_BASE_URL = "https://api.mercadolibre.com"
ML_CATEGORY = "MLU1459"   # Apartamentos en Uruguay

DATA_PATH = Path(__file__).parent.parent / "data" / "apartments.json"
TEST_MODE = "--test" in sys.argv

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ─── Utilidades ───────────────────────────────────────────────────────────────

def normalize(text: str) -> str:
    return (
        str(text).lower().strip()
        .replace("á", "a").replace("é", "e").replace("í", "i")
        .replace("ó", "o").replace("ú", "u").replace("ñ", "n")
    )


def zone_key(name: str) -> str | None:
    """Devuelve la clave de zona normalizada o None si no está en nuestra lista."""
    n = normalize(name)
    for z in ALLOWED_ZONES:
        if z in n or n in z:
            return z
    return None


def rent_uyu(zone: str) -> int:
    return ZONE_RENT_UYU.get(zone, DEFAULT_RENT_UYU)


def calculate_score(rentability_pct: float) -> int:
    return min(100, max(0, round(rentability_pct * 10)))


def parse_days_on_market(html: str) -> int | None:
    patterns = [
        (r"[Pp]ublicado hoy",                1),
        (r"[Pp]ublicado esta semana",         4),
        (r"[Pp]ublicado hace (\d+) d[ií]a",  None),
        (r"[Pp]ublicado hace (\d+) semana",   None),
        (r"[Pp]ublicado hace (\d+) mes",      None),
    ]
    for pattern, fixed in patterns:
        m = re.search(pattern, html, re.IGNORECASE)
        if m:
            if fixed is not None:
                return fixed
            n = int(m.group(1))
            if "semana" in pattern: return n * 7
            if "mes"    in pattern: return n * 30
            return n
    return None


# ─── Tipo de cambio ───────────────────────────────────────────────────────────

def fetch_tc() -> float:
    """Obtiene tipo de cambio USD→UYU desde open.er-api.com (sin API key)."""
    try:
        r = requests.get("https://open.er-api.com/v6/latest/USD", timeout=10)
        r.raise_for_status()
        tc = r.json()["rates"]["UYU"]
        log.info(f"Tipo de cambio USD/UYU: {tc:.2f}")
        return tc
    except Exception as e:
        log.warning(f"No se pudo obtener TC ({e}). Usando valor por defecto: 42.")
        return 42.0


# ─── Autenticación ML API ─────────────────────────────────────────────────────

def get_ml_token() -> str:
    client_id     = os.environ["ML_CLIENT_ID"]
    client_secret = os.environ["ML_CLIENT_SECRET"]
    resp = requests.post(
        f"{ML_BASE_URL}/oauth/token",
        data={
            "grant_type":    "client_credentials",
            "client_id":     client_id,
            "client_secret": client_secret,
        },
        timeout=15,
    )
    resp.raise_for_status()
    log.info("Token ML obtenido correctamente.")
    return resp.json()["access_token"]


# ─── Búsqueda via ML API ──────────────────────────────────────────────────────

def _attr_val(attributes: list, attr_id: str) -> str | None:
    for a in attributes:
        if a.get("id") == attr_id:
            return a.get("value_name")
    return None


def _search_page(token: str, offset: int, limit: int) -> dict:
    resp = requests.get(
        f"{ML_BASE_URL}/sites/{ML_SITE}/search",
        headers={"Authorization": f"Bearer {token}"},
        params={
            "category":   ML_CATEGORY,
            "price_from": MIN_PRICE_USD,
            "price_to":   MAX_PRICE_USD,
            "currency_id": "USD",
            "state_id":   "UY-MO",
            "limit":      limit,
            "offset":     offset,
        },
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


def fetch_all_listings(token: str) -> list[dict]:
    """Pagina la API y devuelve todos los listados en nuestras zonas y rango de precio."""
    listings  = []
    seen_ids  = set()
    offset    = 0
    limit     = 50
    max_pages = 2 if TEST_MODE else 999

    for page_num in range(max_pages):
        log.info(f"API búsqueda — offset={offset}")
        try:
            data = _search_page(token, offset=offset, limit=limit)
        except Exception as e:
            log.error(f"Error en búsqueda API: {e}")
            break

        results = data.get("results", [])
        total   = data.get("paging", {}).get("total", 0)
        log.info(f"  {len(results)} resultados (total disponible en ML: {total})")

        if not results:
            break

        skipped_zone = 0
        for item in results:
            item_id = item.get("id", "")
            if item_id in seen_ids:
                continue
            seen_ids.add(item_id)

            # Precio (ya filtrado por API, pero verificamos)
            price = item.get("price") or 0
            if not (MIN_PRICE_USD <= price <= MAX_PRICE_USD):
                continue

            # Zona
            loc = item.get("location") or {}
            nb_name = (loc.get("neighborhood") or {}).get("name", "")
            zk = zone_key(nb_name)
            if not zk:
                skipped_zone += 1
                continue

            # Atributos
            attrs     = item.get("attributes", [])
            rooms_val = _attr_val(attrs, "BEDROOM_ROOMS") or _attr_val(attrs, "ROOMS")
            m2_raw    = _attr_val(attrs, "TOTAL_AREA") or _attr_val(attrs, "COVERED_AREA")
            m2 = None
            if m2_raw:
                m = re.search(r"(\d+)", m2_raw)
                if m:
                    m2 = int(m.group(1))

            thumbnail = (item.get("thumbnail") or "").replace("http://", "https://")

            listings.append({
                "id":        item_id,
                "title":     item.get("title", ""),
                "price_usd": price,
                "m2":        m2,
                "rooms":     rooms_val or "",
                "zone_key":  zk,
                "zone":      nb_name,
                "location":  loc.get("address_line", nb_name),
                "thumbnail": thumbnail,
                "url":       item.get("permalink", ""),
            })

        log.info(
            f"  En nuestras zonas: {len(listings)} acumulado | "
            f"fuera de zona ignorados: {skipped_zone}"
        )

        offset += limit
        if offset >= total:
            log.info("  Fin de resultados disponibles.")
            break

    log.info(f"Total listados válidos de API: {len(listings)}")
    return listings


# ─── Detalle via Playwright (async, paralelo) ─────────────────────────────────

async def _scrape_detail(semaphore: asyncio.Semaphore, ctx: BrowserContext, url: str) -> dict:
    result = {
        "gastos_comunes_uyu": None,
        "days_on_market":     None,
        "m2_detail":          None,
        "rooms_detail":       None,
    }

    async with semaphore:
        page = await ctx.new_page()
        try:
            await page.goto(url, wait_until="networkidle", timeout=60_000)
            html = await page.content()
        except Exception as e:
            log.warning(f"  Timeout/error: {url[:60]} — {e}")
            await page.close()
            return result
        await page.close()

    soup = BeautifulSoup(html, "lxml")
    table = soup.find(class_=re.compile(r"andes-table"))
    if table:
        for row in table.find_all("tr"):
            cells = row.find_all(["th", "td"])
            if len(cells) < 2:
                continue
            key = normalize(cells[0].get_text(strip=True))
            val = cells[1].get_text(strip=True)

            if "gastos comunes" in key:
                # Siempre en UYU en Uruguay
                m = re.search(r"(\d[\d.,]*)", val)
                if m:
                    result["gastos_comunes_uyu"] = round(
                        float(m.group(1).replace(".", "").replace(",", "."))
                    )

            elif key in ("area privada", "superficie total", "superficie cubierta"):
                if not result["m2_detail"]:
                    m = re.search(r"(\d+)", val)
                    if m:
                        result["m2_detail"] = int(m.group(1))

            elif "dormitorio" in key:
                if val.strip() and val.strip() != "0":
                    result["rooms_detail"] = f"{val} dormitorio(s)"

    result["days_on_market"] = parse_days_on_market(html)
    return result


async def scrape_all_details(listings: list[dict]) -> list[dict]:
    semaphore = asyncio.Semaphore(CONCURRENCY)
    details   = [None] * len(listings)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx     = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
            locale="es-UY",
        )

        async def fetch(i: int, listing: dict):
            log.info(
                f"  [{i+1}/{len(listings)}] {listing['zone']:<12} "
                f"U$S {listing['price_usd']:,.0f} | {listing['title'][:45]}"
            )
            details[i] = await _scrape_detail(semaphore, ctx, listing["url"])

        await asyncio.gather(*[fetch(i, l) for i, l in enumerate(listings)])
        await browser.close()

    return details


# ─── Ensamble final ───────────────────────────────────────────────────────────

def build_apartment(basic: dict, detail: dict, tc: float) -> dict:
    price = basic["price_usd"]
    zone  = basic["zone_key"]
    m2    = detail.get("m2_detail") or basic.get("m2")
    rooms = detail.get("rooms_detail") or basic.get("rooms", "")

    r_uyu         = rent_uyu(zone)
    r_usd         = round(r_uyu / tc)
    rentability   = round((r_uyu * 12) / (price * tc) * 100, 2) if price else 0
    score         = calculate_score(rentability)
    price_per_m2  = round(price / m2) if (m2 and m2 > 0) else None

    return {
        "id":                 basic["id"],
        "title":              basic["title"],
        "price_usd":          price,
        "m2":                 m2,
        "price_per_m2":       price_per_m2,
        "rooms":              rooms,
        "zone":               basic["zone"],
        "location":           basic.get("location", basic["zone"]),
        "gastos_comunes_uyu": detail.get("gastos_comunes_uyu"),
        "estimated_rent_uyu": r_uyu,
        "estimated_rent_usd": r_usd,
        "rentability_pct":    rentability,
        "score":              score,
        "days_on_market":     detail.get("days_on_market"),
        "url":                basic["url"],
        "thumbnail":          basic.get("thumbnail"),
        "source":             "mercadolibre_api",
        "scraped_at":         datetime.utcnow().isoformat() + "Z",
    }


# ─── Guardar ──────────────────────────────────────────────────────────────────

def save_results(apartments: list):
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    output = {
        "last_updated": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total":        len(apartments),
        "max_price_usd": MAX_PRICE_USD,
        "apartments":   apartments,
    }
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    log.info(f"Guardado: {DATA_PATH} ({len(apartments)} apartamentos)")


# ─── Entry point ──────────────────────────────────────────────────────────────

async def main():
    if TEST_MODE:
        log.info("=== MODO TEST (2 páginas API, 3 detalles) ===")
    log.info("=== Scraper Inversiones Montevideo (API + Playwright) ===")

    # 1. Tipo de cambio
    tc = fetch_tc()

    # 2. Token ML
    token = get_ml_token()

    # 3. Búsqueda via API
    listings = fetch_all_listings(token)
    if not listings:
        log.error("Sin resultados. Verifica el token, la categoría ML o los filtros.")
        save_results([])
        return

    # 4. Detalles via Playwright (async + paralelo)
    limit  = 3 if TEST_MODE else len(listings)
    subset = listings[:limit]
    log.info(f"Obteniendo detalles de {len(subset)} apartamentos (CONCURRENCY={CONCURRENCY})...")
    details = await scrape_all_details(subset)

    # 5. Ensamblar
    apartments = [build_apartment(b, d, tc) for b, d in zip(subset, details)]
    apartments.sort(key=lambda x: x["score"], reverse=True)

    log.info(f"\n=== {len(apartments)} apartamentos ===")
    for apt in apartments[:5]:
        log.info(
            f"  Score {apt['score']:3d} | {apt['zone']:<12} | "
            f"U$S {apt['price_usd']:,.0f} | Rent. {apt['rentability_pct']}%"
        )

    save_results(apartments)


if __name__ == "__main__":
    asyncio.run(main())
