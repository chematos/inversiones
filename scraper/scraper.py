#!/usr/bin/env python3
"""
Scraper de apartamentos en Montevideo para inversion inmobiliaria.
Fuente: MercadoLibre Uruguay (via Playwright async - renderizado JS)

Uso:
  python scraper.py          # scrape completo
  python scraper.py --test   # 1 pagina por zona + 10 detalles
"""

import asyncio
import json
import re
import random
import logging
import sys
import requests
from datetime import date, datetime
from pathlib import Path

from playwright.async_api import async_playwright, Page, Browser, BrowserContext
from bs4 import BeautifulSoup

# ─── Configuracion ────────────────────────────────────────────────────────────

MIN_PRICE_USD = 75_000
MAX_PRICE_USD = 98_000

# Zonas permitidas (whitelist)
ALLOWED_ZONES = {"malvin", "malvín", "buceo"}

# Alquiler mensual estimado en UYU por zona (mercado 2025-2026, 1 dorm / monoambiente)
ZONE_RENT_UYU = {
    "buceo":  27_000,
    "malvin": 25_000, "malvín": 25_000,
}
DEFAULT_RENT_UYU = 25_000

TC_FALLBACK = 43.5  # UYU por USD si BCU no responde

CONCURRENCY = 6  # paginas de detalle en paralelo

DATA_PATH = Path(__file__).parent.parent / "data" / "apartments.json"
TEST_MODE = "--test" in sys.argv

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ─── Tipo de cambio BCU ───────────────────────────────────────────────────────

def fetch_tc_usd_uyu() -> float:
    """Obtiene tipo de cambio USD/UYU de open.er-api.com (gratuito, sin key)."""
    try:
        resp = requests.get(
            "https://open.er-api.com/v6/latest/USD",
            timeout=10,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        resp.raise_for_status()
        data = resp.json()
        tc = data["rates"]["UYU"]
        log.info(f"TC USD/UYU: 1 USD = {tc:.2f} UYU (open.er-api.com, {data.get('time_last_update_utc', '')})")
        return tc
    except Exception as e:
        log.warning(f"No se pudo obtener TC: {e}. Usando fallback {TC_FALLBACK}")
    return TC_FALLBACK


# ─── Utilidades ──────────────────────────────────────────────────────────────

def normalize(text: str) -> str:
    return (
        str(text).lower().strip()
        .replace("á", "a").replace("é", "e").replace("í", "i")
        .replace("ó", "o").replace("ú", "u").replace("ñ", "n")
    )


def is_allowed_zone(zone_str: str) -> bool:
    norm = normalize(zone_str)
    for allowed in ALLOWED_ZONES:
        if normalize(allowed) in norm or norm in normalize(allowed):
            return True
    return False


def estimate_rent_uyu(zone_str: str) -> int:
    norm = normalize(zone_str)
    for zone, rent in ZONE_RENT_UYU.items():
        if normalize(zone) in norm or norm in normalize(zone):
            return rent
    return DEFAULT_RENT_UYU


def calculate_score(rentability_pct: float) -> int:
    """Score 0-100. 10% anual = 100 puntos."""
    return min(100, max(0, round(rentability_pct * 10)))


def parse_days_on_market(html_content: str) -> int | None:
    patterns = [
        (r"[Pp]ublicado hoy", 1),
        (r"[Pp]ublicado esta semana", 4),
        (r"[Pp]ublicado hace (\d+) d[ií]a", None),
        (r"[Pp]ublicado hace (\d+) semana", 7),
        (r"[Pp]ublicado hace (\d+) mes", 30),
    ]
    for pattern, fixed_days in patterns:
        m = re.search(pattern, html_content, re.IGNORECASE)
        if m:
            if fixed_days is not None:
                return fixed_days
            return int(m.group(1)) * (7 if "semana" in pattern else 30 if "mes" in pattern else 1)
    return None


# ─── Playwright helpers ──────────────────────────────────────────────────────

async def new_context(browser: Browser) -> BrowserContext:
    return await browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        locale="es-UY",
    )


async def safe_goto(page: Page, url: str, retries: int = 2) -> bool:
    for attempt in range(retries):
        try:
            await page.goto(url, wait_until="networkidle", timeout=60000)
            return True
        except Exception:
            log.warning(f"  Intento {attempt+1} fallido ({url[:60]}): timeout o error de red")
            await asyncio.sleep(random.uniform(4, 8))
    return False


# ─── Scraper de listados de busqueda ────────────────────────────────────────

ML_BASE = "https://listado.mercadolibre.com.uy/inmuebles/apartamentos/venta/propiedades-individuales/montevideo"

ZONE_SLUGS = {
    "Buceo":  "buceo",
    "Malvín": "malvin",
}


def zone_url(zone_slug: str, offset: int = 0) -> str:
    # ML solo acepta PriceRange con min=0; el filtro de precio minimo se aplica en Python
    suffix = f"_OrderId_PRICE_PriceRange_0USD-{MAX_PRICE_USD}USD_NoIndex_True"
    if offset > 0:
        return f"{ML_BASE}/{zone_slug}/_Desde_{offset}{suffix}"
    return f"{ML_BASE}/{zone_slug}/{suffix}"


def parse_search_page(html: str) -> tuple[list[dict], dict]:
    soup = BeautifulSoup(html, "lxml")
    results = []
    stats = {
        "total": 0, "sin_link": 0, "sin_precio": 0,
        "precio_bajo": 0, "precio_alto": 0, "zona_no_permitida": 0, "ok": 0,
    }

    items = [
        li for li in soup.find_all("li", class_="ui-search-layout__item")
        if "intervention" not in " ".join(li.get("class", []))
    ]
    stats["total"] = len(items)

    for item in items:
        try:
            link = item.find("a", href=re.compile(r"mercadolibre\.com\.uy"))
            if not link:
                stats["sin_link"] += 1
                continue
            url = link["href"].split("?")[0].split("#")[0]

            price_span = item.find(attrs={"aria-label": re.compile(r"\d+\s+dólares", re.IGNORECASE)})
            if not price_span:
                stats["sin_precio"] += 1
                continue
            price_match = re.search(r"(\d[\d.]*)\s+dólares", price_span["aria-label"], re.IGNORECASE)
            if not price_match:
                stats["sin_precio"] += 1
                continue
            price = float(price_match.group(1).replace(".", ""))
            if price < MIN_PRICE_USD:
                stats["precio_bajo"] += 1
                continue
            if price > MAX_PRICE_USD:
                stats["precio_alto"] += 1
                continue

            loc_el = item.find(class_="poly-component__location")
            location = loc_el.get_text(strip=True) if loc_el else ""

            zone = "Desconocida"
            tag_el = item.find(class_="andes-tag__label")
            if tag_el:
                tag_text = tag_el.get_text(strip=True)
                if is_allowed_zone(tag_text):
                    zone = tag_text
            if zone == "Desconocida":
                for part in [p.strip() for p in location.split(",")]:
                    if is_allowed_zone(part):
                        zone = part
                        break

            if zone == "Desconocida":
                stats["zona_no_permitida"] += 1
                continue
            stats["ok"] += 1

            title_el = item.find(class_="poly-component__title")
            title = title_el.get_text(strip=True) if title_el else "Sin titulo"

            attr_items = item.find_all(class_="poly-attributes_list__item")
            attrs = [a.get_text(strip=True) for a in attr_items]
            rooms_text = next(
                (a for a in attrs if "dormitorio" in a.lower() or "monoambiente" in a.lower()), ""
            )
            m2 = None
            for a in attrs:
                m = re.search(r"(\d+)\s*m²", a, re.IGNORECASE)
                if m:
                    m2 = int(m.group(1))
                    break

            img = item.find("img", src=re.compile(r"http"))
            thumbnail = img["src"] if img else None

            results.append({
                "url": url,
                "title": title,
                "price_usd": price,
                "m2": m2,
                "rooms": rooms_text,
                "zone": zone,
                "location": location,
                "thumbnail": thumbnail,
            })

        except Exception as e:
            log.debug(f"  Error parseando item: {e}")

    return results, stats


async def scrape_zone(
    page: Page, zone_name: str, zone_slug: str, seen_urls: set, max_pages: int
) -> list[dict]:
    zone_listings = []
    offset = 0
    pg = 1

    log.info(f"[ML] Zona: {zone_name}")

    while pg <= max_pages:
        url = zone_url(zone_slug, offset)
        log.info(f"  Pagina {pg}: {url}")

        if not await safe_goto(page, url):
            log.warning(f"  No se pudo cargar pagina {pg}. Saltando.")
            break

        html = await page.content()
        listings, stats = parse_search_page(html)
        new = [l for l in listings if l["url"] not in seen_urls]
        for l in new:
            seen_urls.add(l["url"])
        zone_listings.extend(new)
        log.info(
            f"  {stats['total']} items | "
            f"sin_precio={stats['sin_precio']} bajo={stats['precio_bajo']} alto={stats['precio_alto']} "
            f"zona_off={stats['zona_no_permitida']} | "
            f"validos={len(new)} (acum zona: {len(zone_listings)})"
        )

        soup = BeautifulSoup(html, "lxml")
        next_btn = soup.find(class_=re.compile(r"andes-pagination__button--next"))
        if not next_btn or next_btn.get("disabled"):
            log.info("  Ultima pagina de la zona.")
            break

        offset = pg * 48 + 1
        pg += 1
        await asyncio.sleep(random.uniform(1.5, 3))

    return zone_listings


async def scrape_all_listings(browser: Browser) -> list[dict]:
    """Scrapea todas las zonas secuencialmente (evita rate limiting en busqueda)."""
    all_listings = []
    seen_urls = set()
    max_pages = 1 if TEST_MODE else 20

    ctx = await new_context(browser)
    page = await ctx.new_page()

    for zone_name, zone_slug in ZONE_SLUGS.items():
        zone_listings = await scrape_zone(page, zone_name, zone_slug, seen_urls, max_pages)
        all_listings.extend(zone_listings)
        await asyncio.sleep(random.uniform(2, 4))

    await ctx.close()
    return all_listings


# ─── Scraper de detalle (async, concurrente) ──────────────────────────────────

async def scrape_detail(browser: Browser, url: str, sem: asyncio.Semaphore) -> dict:
    result = {
        "gastos_comunes_uyu": None,
        "gastos_comunes_raw": None,
        "days_on_market": None,
        "m2_detail": None,
        "rooms_detail": None,
    }

    async with sem:
        ctx = await new_context(browser)
        page = await ctx.new_page()
        try:
            if not await safe_goto(page, url):
                return result

            html = await page.content()
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
                            amount = float(m.group(1).replace(".", "").replace(",", "."))
                            result["gastos_comunes_uyu"] = round(amount)
                            result["gastos_comunes_raw"] = amount

                    elif key in ("area privada", "superficie total", "superficie cubierta"):
                        if not result["m2_detail"]:
                            m = re.search(r"(\d+)", val)
                            if m:
                                result["m2_detail"] = int(m.group(1))

                    elif "dormitorio" in key:
                        if val.strip() and val.strip() != "0":
                            result["rooms_detail"] = f"{val} dormitorio(s)"

            result["days_on_market"] = parse_days_on_market(html)

        finally:
            await ctx.close()

    return result


# ─── Pipeline principal ──────────────────────────────────────────────────────

def build_apartment(basic: dict, detail: dict, tc: float) -> dict:
    price = basic["price_usd"]
    m2 = detail.get("m2_detail") or basic.get("m2")
    rooms = detail.get("rooms_detail") or basic.get("rooms", "")
    zone = basic["zone"]

    estimated_rent_uyu = estimate_rent_uyu(zone)
    estimated_rent_usd = round(estimated_rent_uyu / tc)
    rentability_pct = round((estimated_rent_uyu * 12) / (price * tc) * 100, 2) if (price and tc) else 0
    price_per_m2 = round(price / m2) if (m2 and m2 > 0) else None
    score = calculate_score(rentability_pct)

    apt_id_match = re.search(r"MLU[-_]?(\d+)", basic["url"])
    apt_id = f"MLU-{apt_id_match.group(1)}" if apt_id_match else basic["url"][-20:]

    return {
        "id": apt_id,
        "title": basic["title"],
        "price_usd": price,
        "m2": m2,
        "price_per_m2": price_per_m2,
        "rooms": rooms,
        "zone": zone,
        "location": basic.get("location", zone),
        "gastos_comunes_uyu": detail.get("gastos_comunes_uyu"),
        "gastos_comunes_raw": detail.get("gastos_comunes_raw"),
        "estimated_rent_uyu": estimated_rent_uyu,
        "estimated_rent_usd": estimated_rent_usd,
        "rentability_pct": rentability_pct,
        "score": score,
        "days_on_market": detail.get("days_on_market"),
        "url": basic["url"],
        "thumbnail": basic.get("thumbnail"),
        "source": "mercadolibre",
        "scraped_at": datetime.utcnow().isoformat() + "Z",
    }


async def run():
    if TEST_MODE:
        log.info("=== MODO TEST (1 pagina por zona, 10 detalles) ===")
    log.info("=== Scraper Inversiones Montevideo ===")
    log.info(f"Precio: U$S {MIN_PRICE_USD:,} – {MAX_PRICE_USD:,} | Zonas: {', '.join(ZONE_SLUGS)} | Concurrencia: {CONCURRENCY}")

    # Tipo de cambio (sync, antes de entrar al loop async)
    tc = fetch_tc_usd_uyu()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        # 1. Listados (secuencial por zona para no gatillar rate limiting)
        basic_listings = await scrape_all_listings(browser)
        log.info(f"\nTotal listados validos: {len(basic_listings)}")

        if not basic_listings:
            log.error("No se encontraron listados. Verifica la conexion o los selectores.")
            await browser.close()
            save_results([], tc)
            return

        # 2. Detalles en paralelo
        limit = 10 if TEST_MODE else len(basic_listings)
        to_process = basic_listings[:limit]
        log.info(f"Obteniendo detalles de {len(to_process)} listados ({CONCURRENCY} en paralelo)...")

        sem = asyncio.Semaphore(CONCURRENCY)
        completed = 0

        async def fetch_one(basic: dict) -> dict:
            nonlocal completed
            detail = await scrape_detail(browser, basic["url"], sem)
            completed += 1
            if completed % 25 == 0 or completed == len(to_process):
                log.info(f"  Detalles: {completed}/{len(to_process)}")
            return detail

        details = await asyncio.gather(*[fetch_one(b) for b in to_process])

        await browser.close()

    apartments = [
        build_apartment(basic, detail, tc)
        for basic, detail in zip(to_process, details)
    ]
    apartments.sort(key=lambda x: x["score"], reverse=True)

    log.info(f"\n=== Resultado final: {len(apartments)} apartamentos ===")
    for apt in apartments[:5]:
        log.info(
            f"  Score {apt['score']:3d} | {apt['zone']:<12} | "
            f"U$S {apt['price_usd']:,.0f} | Rent. {apt['rentability_pct']}% | "
            f"Alq. $U {apt['estimated_rent_uyu']:,}/mes"
        )

    save_results(apartments, tc)


def save_results(apartments: list, tc: float = TC_FALLBACK):
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    output = {
        "last_updated": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total": len(apartments),
        "min_price_usd": MIN_PRICE_USD,
        "max_price_usd": MAX_PRICE_USD,
        "tc_usd_uyu": tc,
        "apartments": apartments,
    }
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    log.info(f"Datos guardados en {DATA_PATH}")


if __name__ == "__main__":
    asyncio.run(run())
