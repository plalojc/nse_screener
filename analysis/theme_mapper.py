# ============================================================
# analysis/theme_mapper.py - Policy/news theme to NSE symbol mapper
# ============================================================
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable

import requests

from config import CATALYST_SOURCE_TIMEOUT, ENABLE_ONLINE_THEME_SOURCES


NSE_INDEX_ARCHIVE = "https://nsearchives.nseindia.com/content/indices"


@dataclass(frozen=True)
class ThemeDefinition:
    key: str
    label: str
    keywords: tuple[str, ...]
    seed_symbols: tuple[str, ...]
    priority: int
    source: str = "LOCAL_SEED"
    index_files: tuple[str, ...] = ()


@dataclass(frozen=True)
class ThemeMatch:
    key: str
    label: str
    score: int
    confidence: int
    source: str
    reason: str
    symbols: tuple[str, ...]


THEME_DEFINITIONS: tuple[ThemeDefinition, ...] = (
    ThemeDefinition(
        key="defence",
        label="Defence manufacturing",
        keywords=(
            "defence", "defense", "armed forces", "indigenisation",
            "indigenization", "make in india", "aerospace", "missile",
            "shipbuilding", "warship", "drone", "uav", "radar",
        ),
        seed_symbols=(
            "HAL", "BEL", "BEML", "BDL", "MAZDOCK", "COCHINSHIP",
            "DATAPATTNS", "PARAS", "MTARTECH", "GRSE", "ASTRAMICRO",
            "DCXINDIA", "IDEAFORGE", "SOLARINDS", "ZENTEC",
        ),
        priority=10,
        index_files=("ind_niftyindiadefencelist.csv", "ind_niftyinddefencelist.csv"),
    ),
    ThemeDefinition(
        key="railway",
        label="Railways and rolling stock",
        keywords=(
            "railway", "railways", "rail", "metro rail", "vande bharat",
            "wagon", "freight corridor", "station redevelopment",
            "rail infrastructure",
        ),
        seed_symbols=(
            "RVNL", "IRCON", "RAILTEL", "IRFC", "BEML", "TITAGARH",
            "TEXRAIL", "JWL", "RITES", "IRCTC", "KERNEX", "HBLPOWER",
            "JYOTISTRUC", "KALPATARU",
        ),
        priority=9,
        index_files=("ind_niftytransportationlogisticslist.csv",),
    ),
    ThemeDefinition(
        key="renewable",
        label="Renewable energy",
        keywords=(
            "renewable", "green energy", "solar", "wind energy",
            "green hydrogen", "energy transition", "battery storage",
            "clean energy", "rooftop solar", "pm surya ghar",
        ),
        seed_symbols=(
            "ADANIGREEN", "TATAPOWER", "NTPC", "SJVN", "NHPC", "JSWENERGY",
            "INOXWIND", "SUZLON", "WAAREEENER", "BORORENEW", "WEBELSOLAR",
            "KPI", "KPIGREEN", "IREDA", "OLECTRA",
        ),
        priority=9,
        index_files=("ind_niftyenergylist.csv", "ind_niftyev_newagelist.csv"),
    ),
    ThemeDefinition(
        key="power_grid",
        label="Power transmission and utilities",
        keywords=(
            "power transmission", "grid", "transmission line", "power sector",
            "electricity distribution", "smart meter", "discom",
        ),
        seed_symbols=(
            "POWERGRID", "TATAPOWER", "ADANITRANS", "ADANIENSOL",
            "KEC", "KALPATARU", "SIEMENS", "ABB", "CGPOWER", "HPL",
            "GENUSPOWER",
        ),
        priority=7,
    ),
    ThemeDefinition(
        key="infrastructure",
        label="Infrastructure and construction",
        keywords=(
            "infrastructure", "highway", "road project", "bharatmala",
            "expressway", "airport", "port", "urban infrastructure",
            "capital expenditure", "capex outlay", "construction",
        ),
        seed_symbols=(
            "LT", "NCC", "PNCINFRA", "KNRCON", "IRB", "ASHOKA", "GRINFRA",
            "HGIEL", "KEC", "KALPATARU", "NBCC", "HUDCO", "CONCOR",
            "ADANIPORTS", "GMRINFRA",
        ),
        priority=8,
        index_files=("ind_niftyinfralist.csv", "ind_niftyindiamanufacturinglist.csv"),
    ),
    ThemeDefinition(
        key="cement",
        label="Cement and building materials",
        keywords=(
            "cement", "housing", "real estate", "affordable housing",
            "rural housing", "construction material", "building material",
        ),
        seed_symbols=(
            "ULTRACEMCO", "AMBUJACEM", "ACC", "DALBHARAT", "JKCEMENT",
            "RAMCOCEM", "SHREECEM", "INDIACEM", "NUVOCO", "ORIENTCEM",
        ),
        priority=6,
    ),
    ThemeDefinition(
        key="auto_ev",
        label="EV and auto mobility",
        keywords=(
            "electric vehicle", "ev", "vehicle scrappage", "automobile",
            "auto sector", "battery", "charging infrastructure", "mobility",
            "fame", "pm e-drive",
        ),
        seed_symbols=(
            "TATAMOTORS", "M&M", "MARUTI", "BAJAJ-AUTO", "HEROMOTOCO",
            "TVSMOTOR", "EICHERMOT", "EXIDEIND", "AMARAJABAT", "OLECTRA",
            "JBM AUTO", "SONACOMS", "MOTHERSON", "UNOMINDA", "BOSCHLTD",
        ),
        priority=8,
        index_files=("ind_niftyautolist.csv", "ind_niftyev_newagelist.csv", "ind_niftymobilitylist.csv"),
    ),
    ThemeDefinition(
        key="electronics_semiconductor",
        label="Electronics and semiconductors",
        keywords=(
            "semiconductor", "chip", "electronics manufacturing",
            "production linked incentive", "pli scheme", "display fab",
            "component manufacturing", "ems", "mobile manufacturing",
        ),
        seed_symbols=(
            "DIXON", "KAYNES", "SYRMA", "PGEL", "AMBER", "CGPOWER",
            "TATAELXSI", "MOSCHIP", "HCLTECH", "LTTS", "CYIENT",
            "CENTUM", "AVALON",
        ),
        priority=9,
        index_files=("ind_niftyindiadigital_list.csv", "ind_niftyitlist.csv"),
    ),
    ThemeDefinition(
        key="pharma_healthcare",
        label="Pharma and healthcare",
        keywords=(
            "pharma", "pharmaceutical", "healthcare", "hospital",
            "medical device", "usfda", "drug approval", "clinical trial",
            "api manufacturing", "bulk drug",
        ),
        seed_symbols=(
            "SUNPHARMA", "CIPLA", "DRREDDY", "LUPIN", "AUROPHARMA",
            "DIVISLAB", "ZYDUSLIFE", "TORNTPHARM", "GLENMARK",
            "ALKEM", "APOLLOHOSP", "FORTIS", "MAXHEALTH", "NATCOPHARM",
        ),
        priority=8,
        index_files=("ind_niftypharmalist.csv", "ind_niftyhealthcarelist.csv"),
    ),
    ThemeDefinition(
        key="sugar_ethanol",
        label="Sugar and ethanol blending",
        keywords=(
            "ethanol", "sugar", "sugarcane", "blending", "distillery",
            "biofuel", "molasses",
        ),
        seed_symbols=(
            "BALRAMCHIN", "TRIVENI", "EIDPARRY", "DHAMPURSUG", "RENUKA",
            "DALMIASUG", "DWARKESH", "AVADHSUGAR", "BAJAJHIND",
            "PRAJIND",
        ),
        priority=7,
    ),
    ThemeDefinition(
        key="fertiliser_agri",
        label="Fertiliser and agriculture",
        keywords=(
            "fertiliser", "fertilizer", "urea", "subsidy", "agriculture",
            "crop", "kharif", "rabi", "irrigation", "farm mechanisation",
            "farm mechanization", "food processing",
        ),
        seed_symbols=(
            "CHAMBLFERT", "GNFC", "GSFC", "RCF", "NFL", "FACT",
            "COROMANDEL", "DEEPAKFERT", "UPL", "PIIND", "ESCORTS",
            "VSTTILLERS", "JUBLFOOD",
        ),
        priority=6,
    ),
    ThemeDefinition(
        key="banking_credit",
        label="Banking and credit growth",
        keywords=(
            "banking", "credit growth", "nbfc", "housing finance",
            "interest rate cut", "liquidity", "rbi policy", "repo rate",
            "msme credit",
        ),
        seed_symbols=(
            "HDFCBANK", "ICICIBANK", "SBIN", "AXISBANK", "KOTAKBANK",
            "BANKBARODA", "PNB", "CANBK", "AUBANK", "BAJFINANCE",
            "CHOLAFIN", "LICHSGFIN", "RECLTD", "PFC", "HUDCO",
        ),
        priority=5,
        index_files=("ind_niftybanklist.csv", "ind_niftypsubanklist.csv", "ind_niftyfinancelist.csv"),
    ),
    ThemeDefinition(
        key="telecom_digital",
        label="Telecom and digital infrastructure",
        keywords=(
            "telecom", "5g", "broadband", "data centre", "data center",
            "digital india", "satellite communication", "spectrum",
        ),
        seed_symbols=(
            "BHARTIARTL", "INDUSTOWER", "TEJASNET", "HFCL", "STLTECH",
            "RAILTEL", "TATACOMM", "ROUTE", "TANLA", "NETWEB",
        ),
        priority=6,
    ),
)


def _normalise_symbol(value: str | None) -> str:
    return re.sub(r"\s+", "", str(value or "").strip().upper())


def _normalise_text(value: str | None) -> str:
    text = str(value or "").lower()
    text = re.sub(r"[^a-z0-9&+.\-\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _phrase_score(text: str, keyword: str) -> int:
    keyword_norm = _normalise_text(keyword)
    if not keyword_norm or keyword_norm not in text:
        return 0
    words = keyword_norm.split()
    if len(words) >= 2:
        return 4 + min(3, len(words))
    return 3


def _safe_get_text(url: str) -> str | None:
    if not ENABLE_ONLINE_THEME_SOURCES:
        return None
    try:
        response = requests.get(
            url,
            timeout=CATALYST_SOURCE_TIMEOUT,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
                ),
                "Accept": "text/csv,text/plain,*/*",
            },
        )
        response.raise_for_status()
        return response.text
    except Exception:
        return None


def _symbols_from_csv(text: str, universe: set[str]) -> set[str]:
    symbols: set[str] = set()
    try:
        reader = csv.DictReader(io.StringIO(text))
        for row in reader:
            for key in ("Symbol", "SYMBOL", "symbol", "Ticker", "ticker"):
                symbol = _normalise_symbol(row.get(key))
                if symbol in universe:
                    symbols.add(symbol)
                    break
    except Exception:
        return set()
    return symbols


@lru_cache(maxsize=16)
def _online_symbols_for_theme(theme_key: str, universe_key: tuple[str, ...]) -> tuple[str, ...]:
    universe = set(universe_key)
    theme = next((item for item in THEME_DEFINITIONS if item.key == theme_key), None)
    if not theme or not theme.index_files:
        return ()

    symbols: set[str] = set()
    for filename in theme.index_files:
        text = _safe_get_text(f"{NSE_INDEX_ARCHIVE}/{filename}")
        if not text:
            continue
        symbols.update(_symbols_from_csv(text, universe))
    return tuple(sorted(symbols))


@lru_cache(maxsize=16)
def _build_theme_symbol_map_cached(universe_key: tuple[str, ...]) -> dict[str, tuple[str, ...]]:
    universe = set(universe_key)
    mapping: dict[str, tuple[str, ...]] = {}
    for theme in THEME_DEFINITIONS:
        symbols = {symbol for symbol in theme.seed_symbols if symbol in universe}
        symbols.update(_online_symbols_for_theme(theme.key, universe_key))
        mapping[theme.key] = tuple(sorted(symbols))
    return mapping


def build_theme_symbol_map(universe_symbols: Iterable[str]) -> dict[str, tuple[str, ...]]:
    universe = {_normalise_symbol(s) for s in universe_symbols}
    universe.discard("")
    universe_key = tuple(sorted(universe))
    return _build_theme_symbol_map_cached(universe_key)


def match_policy_themes(
    title: str,
    body: str,
    universe_symbols: Iterable[str],
    max_themes: int = 3,
) -> list[ThemeMatch]:
    """Return likely beneficiary themes for a government/policy item."""
    text = _normalise_text(f"{title} {body}")
    if not text:
        return []

    theme_symbols = build_theme_symbol_map(universe_symbols)
    matches: list[ThemeMatch] = []
    for theme in THEME_DEFINITIONS:
        keyword_score = sum(_phrase_score(text, keyword) for keyword in theme.keywords)
        if keyword_score <= 0:
            continue

        symbols = theme_symbols.get(theme.key, ())
        if not symbols:
            continue

        score = min(12, theme.priority + keyword_score)
        confidence = min(10, 4 + keyword_score + (1 if theme.index_files else 0))
        source = "NSE_INDEX_OR_SEED" if theme.index_files else theme.source
        matched_words = [
            keyword for keyword in theme.keywords
            if _normalise_text(keyword) in text
        ][:4]
        reason = ", ".join(matched_words) if matched_words else theme.label
        matches.append(ThemeMatch(
            key=theme.key,
            label=theme.label,
            score=score,
            confidence=confidence,
            source=source,
            reason=reason,
            symbols=symbols,
        ))

    matches.sort(key=lambda item: (item.score, item.confidence, len(item.symbols)), reverse=True)
    return matches[:max_themes]
