"""
Backend web de Ourania (vpardo.com/ourania) — fork del sidecar de escritorio,
adaptado para correr como función serverless en Vercel (@vercel/python).

Sin persistencia, sin auth: cada carta se calcula al vuelo y no se guarda
nada acá (SIN base de datos). Motor Moshier siempre (no se bundlean
sepl_18.se1/semo_18.se1 — ver sidecar/main.py para el motor completo, que
es solo para uso de escritorio privado). Esto es intencional y no un
descuido: Swiss Ephemeris exige AGPL (código abierto) o licencia paga para
CUALQUIER software accesible por red — este archivo es público en GitHub
por eso mismo, es la forma de cumplir sin pagar. No confundir con el resto
del código de Ourania (desktop), que sigue siendo privado.

REGLA: ninguna posición astrológica puede originarse en el LLM — TODA
efeméride sale de acá (Swiss Ephemeris, modo Moshier: sin archivos externos,
precisión ~0.1" para planetas).

Forkeado del sidecar de ORÁCULO (mismo motor pyswisseph, mismas técnicas de
retorno solar/lunar, progresiones, cruce de cartas). Se eliminaron /windows
y /batch (específicos del caso de uso deportivo de ORÁCULO). Los endpoints
nuevos de Astrario (direcciones, ARMC, estrellas fijas, partes árabes,
puntos medios, armónicas, astrocartografía — ver plan F3-F5) se suman acá
a medida que avanzan las fases.

Endpoints:
  GET  /health
  POST /chart        {date, time?, lat?, lon?, time_quality} → posiciones (+casas/ASC solo si hay hora)
  POST /transits     {radix: [{name, lon}], date} → aspectos aplicativos con orbes
  POST /solar_return {natal_date, natal_time?, year, lat?, lon?} → carta del retorno solar
  POST /lunar_return {natal_date, natal_time?, target_date, lat?, lon?} → revolución lunar (reubicable en sede)
  POST /progressions {natal_date, natal_time?, target_date} → progresiones secundarias (1 día = 1 año)
  POST /cross        {a: [...], b: [...]} → aspectos entre dos cartas (sinastría genérica)
  POST /symbolic_directions {natal_date, natal_time?, target_date, key, lat?, lon?} → dirección de arco uniforme (ptolemy/naibod/duodenary/pythagorean/c60)
  POST /arabic_parts {natal_date, natal_time, lat, lon} → Parte de la Fortuna (diurna/nocturna)
  POST /midpoints    {points: [...], orb?} → puntos medios + árbol dial 90° (Ebertin)
  POST /harmonic     {points: [...], harmonic} → carta armónica H
  POST /armc         {date, time, lat, lon} → ARMC, RA/Dec/AD/OA por planeta+ASC+MC (base ascensional/topocéntrica)
  POST /fixed_stars  {date, time, names} → posición de estrellas fijas (ÚNICO endpoint con archivo externo: ephe/sefstars.txt)
  POST /primary_directions {armc, lat, promissor, significator, key} → arco semi-diurno (Placidus, en mundo) — ver advertencia de convención en el docstring del endpoint
  POST /astrocartography {date, time, points?, lat_step?} → líneas MC/IC/ASC/DESC de cada planeta sobre el mapa
  POST /eclipses_and_lunations {date, time?} → próxima luna nueva/llena + próximo eclipse solar/lunar (globales)
  POST /rectify      {natal_date, lat, lon, time_from?, time_to?, events: [{date, label?}]} → candidatas de hora natal rankeadas por direcciones primarias a eventos
  POST /dignities    {points: [{name, lon}], is_day} → dignidades esenciales (domicilio/exaltación/detrimento/caída/triplicidad/término/rostro) + Almutem Figuris por punto
"""
from __future__ import annotations

import math
import os
import sys

import swisseph as swe
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional


def _ensure_ephe_path() -> None:
    """swe.set_ephe_path() en Vercel: los endpoints sync de FastAPI corren
    en threads del threadpool de Starlette, uno distinto por request (o al
    menos no necesariamente el thread de import del módulo) — y el estado
    de ephe path de pyswisseph resultó ser thread-local ahí (aunque en el
    sidecar de escritorio, un solo proceso uvicorn sin ese threadpool
    dinámico, alcanzaba con setearlo una vez al importar). Sin esto: swe
    caía a paths default hardcodeados tipo "/users/ephe/" y tiraba
    "file not found" pese a que el archivo SÍ estaba en el deploy — bug
    real encontrado en producción, no hipotético. Se cuelga como
    dependencia global para que corra en el thread correcto en cada
    request, sin tocar cada endpoint a mano."""
    swe.set_ephe_path(_EPHE_DIR)


app = FastAPI(title="ourania-web-api", dependencies=[Depends(_ensure_ephe_path)])

# público sin auth por diseño (ver docstring del módulo) — cualquiera con
# el link tiene que poder pegarle a esto desde el navegador, no hay sesión
# ni cookie que proteger.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def _ephe_path() -> str:
    """dev: sidecar/ephe/ junto a este archivo. Empaquetado (PyInstaller
    --onefile): los datos van a sys._MEIPASS, no al cwd del proceso."""
    base = getattr(sys, '_MEIPASS', None)
    if base:
        return os.path.join(base, 'ephe')
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ephe')


_EPHE_DIR = _ephe_path()
swe.set_ephe_path(_EPHE_DIR)

# sepl_18.se1/semo_18.se1 (planetas y Luna, 1800-2399) dan el motor de
# archivo completo (FLG_SWIEPH) — precisión de fracción de segundo de
# arco, pero Swiss Ephemeris es AGPL/dual-license y el archivo completo
# solo es gratis (AGPL) para uso PRIVADO sin distribuir. La presencia de
# esos dos archivos decide el motor, así que alcanza con no incluirlos en
# el --add-data de un build para no violar la licencia:
# - `npm run build:sidecar` (uso propio de Victor): los suma → motor completo.
# - `npm run build:sidecar:dist` (build para darle a OTRA gente a probar):
#   NO los suma → cae solo a Moshier, que es gratis para cualquier uso,
#   incluida la distribución. Ver nota de licencia completa en CLAUDE.md
#   antes de tocar esto — el día que se venda/distribuya con el motor
#   completo hay que pagar la licencia profesional de Astrodienst primero.
_HAS_FULL_EPHEMERIS = os.path.isfile(os.path.join(_EPHE_DIR, 'sepl_18.se1'))

PLANETS = {
    "Sol": swe.SUN, "Luna": swe.MOON, "Mercurio": swe.MERCURY, "Venus": swe.VENUS,
    "Marte": swe.MARS, "Júpiter": swe.JUPITER, "Saturno": swe.SATURN,
    "Urano": swe.URANUS, "Neptuno": swe.NEPTUNE, "Plutón": swe.PLUTO,
    # Quirón necesita seas_18.se1 (único cuerpo del set que no cubre Moshier
    # analítico) — mismo patrón que sefstars.txt para estrellas fijas.
    # Lilith = apogeo lunar medio, geométrico puro, no necesita archivo.
    "Quirón": swe.CHIRON, "Lilith": swe.MEAN_APOG,
}
SIGNS = ["Aries", "Tauro", "Géminis", "Cáncer", "Leo", "Virgo", "Libra",
         "Escorpio", "Sagitario", "Capricornio", "Acuario", "Piscis"]
FLAGS = (swe.FLG_SWIEPH if _HAS_FULL_EPHEMERIS else swe.FLG_MOSEPH) | swe.FLG_SPEED

# Sistemas de casas soportados (letra que espera swe.houses) — set profesional
# estándar; astroseek/Meridian ofrecen el mismo abanico.
HOUSE_SYSTEMS = {
    "placidus": b"P", "koch": b"K", "regiomontanus": b"R", "campanus": b"C",
    "equal": b"E", "whole_sign": b"W", "porphyry": b"O", "alcabitius": b"B",
    "topocentric": b"T", "morinus": b"M",
}

# aspectos: (nombre, ángulo, mayor?)
ASPECTS = [
    ("conjunción", 0, True), ("sextil", 60, True), ("cuadratura", 90, True),
    ("trígono", 120, True), ("oposición", 180, True),
    ("semisextil", 30, False), ("semicuadratura", 45, False),
    ("sesquicuadratura", 135, False), ("quincuncio", 150, False),
]


def jd_from(date: str, time: Optional[str]) -> float:
    y, m, d = (int(x) for x in date.split("-"))
    hour = 12.0
    if time:
        hh, mm = (int(x) for x in time.split(":")[:2])
        hour = hh + mm / 60.0
    return swe.julday(y, m, d, hour)


def positions(jd: float) -> list[dict]:
    out = []
    for name, pid in PLANETS.items():
        (lon, lat, dist, lon_speed, *_), _ = swe.calc_ut(jd, pid, FLAGS)
        out.append({
            "name": name,
            "lon": round(lon, 6),
            "sign": SIGNS[int(lon // 30)],
            "sign_degree": round(lon % 30, 4),
            "speed": round(lon_speed, 6),
            "retrograde": lon_speed < 0,
        })
    return out


def sep(a: float, b: float) -> float:
    d = abs(a - b) % 360.0
    return min(d, 360.0 - d)


def lunar_node(jd: float, true_node: bool) -> dict:
    """Nodo lunar (eje de nodos) — True (osculante, se mueve retrógrado con
    tumbos) o Mean (promedio, retrógrado uniforme). El Sur es siempre el
    Norte + 180°, nunca se calcula por separado."""
    pid = swe.TRUE_NODE if true_node else swe.MEAN_NODE
    (lon, _lat, _dist, speed, *_), _ = swe.calc_ut(jd, pid, FLAGS)
    south = (lon + 180.0) % 360.0
    return {
        "north": {"lon": round(lon, 6), "sign": SIGNS[int(lon // 30)],
                   "sign_degree": round(lon % 30, 4), "retrograde": speed < 0},
        "south": {"lon": round(south, 6), "sign": SIGNS[int(south // 30)],
                   "sign_degree": round(south % 30, 4), "retrograde": speed < 0},
    }


def house_bytes(house_system: str) -> bytes:
    return HOUSE_SYSTEMS.get(house_system, b"P")


def house_of(lon: float, cusps: list[float]) -> int:
    """Mismo algoritmo que core/services/houses.ts::houseOf (TS) — portado
    acá para no depender del front para saber en qué casa cae un grado."""
    for i in range(12):
        start, end = cusps[i], cusps[(i + 1) % 12]
        in_range = (lon >= start and lon < end) if end > start else (lon >= start or lon < end)
        if in_range:
            return i + 1
    return 1


def dial_diff(a: float, b: float, modulus: float = 90.0) -> float:
    """Distancia angular entre dos grados sobre un dial de `modulus`° (el
    dial de 90° de Ebertin pliega conjunción/cuadratura/oposición en un
    solo chequeo: dos puntos a 0/90/180/270° entre sí caen en el MISMO
    lugar del dial)."""
    d = abs((a % modulus) - (b % modulus)) % modulus
    return min(d, modulus - d)


class ChartReq(BaseModel):
    date: str                    # YYYY-MM-DD
    time: Optional[str] = None   # HH:MM (UTC)
    lat: Optional[float] = None
    lon: Optional[float] = None
    time_quality: str = "exact"  # exact | approx | unknown
    house_system: str = "placidus"  # ver HOUSE_SYSTEMS
    node_type: str = "true"         # true | mean


@app.get("/health")
def health() -> dict:
    engine = "swisseph-full" if _HAS_FULL_EPHEMERIS else "swisseph-moshier"
    return {"ok": True, "engine": engine, "version": swe.version}


# --- buscador de ciudad propio (GeoNames cities15000, ~34k ciudades) ---
# reemplaza la dependencia de Open-Meteo del frontend: pocos resultados
# (count=5 fijo) y búsquedas que se pisaban entre sí sin un guard de
# "solo la última cuenta" — con esto el buscador es propio, más grande,
# y el orden/cancelación de requests se controla client-side con un id
# de request creciente (ver public/index.html).
import gzip
import json
import unicodedata

with gzip.open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "cities.json.gz"), "rt", encoding="utf-8") as _f:
    _CITIES = json.load(_f)


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


_CITIES_NORM = [_norm(c["n"]) for c in _CITIES]


@app.get("/geocode")
def geocode(q: str, count: int = 8) -> dict:
    query = _norm(q.strip())
    if not query:
        return {"results": []}
    prefix, contains = [], []
    for city, name_norm in zip(_CITIES, _CITIES_NORM):
        if name_norm.startswith(query):
            prefix.append(city)
        elif query in name_norm:
            contains.append(city)
        if len(prefix) >= count * 3:
            break
    results = (prefix + contains)[: count * 2]
    # ya vienen ordenadas por población (ver build.py) — dedup liviano por
    # nombre+país para no repetir el mismo lugar dos veces
    seen = set()
    out = []
    for c in results:
        key = (c["n"], c["c"])
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
        if len(out) >= count:
            break
    return {
        "results": [
            {"name": c["n"], "admin1": c["a"], "country": c["c"], "lat": c["lat"], "lon": c["lon"], "timezone": c["tz"]}
            for c in out
        ]
    }


@app.post("/chart")
def chart(req: ChartReq) -> dict:
    has_time = req.time is not None and req.time_quality != "unknown"
    jd = jd_from(req.date, req.time if has_time else None)
    plist = positions(jd)

    moon_range = None
    if not has_time:
        # sin hora la Luna se informa como RANGO del día, nunca como grado
        jd0 = jd_from(req.date, "00:00")
        jd1 = jd_from(req.date, "23:59")
        (l0, *_), _ = swe.calc_ut(jd0, swe.MOON, FLAGS)
        (l1, *_), _ = swe.calc_ut(jd1, swe.MOON, FLAGS)
        moon_range = {
            "from": {"lon": round(l0, 4), "sign": SIGNS[int(l0 // 30)]},
            "to": {"lon": round(l1, 4), "sign": SIGNS[int(l1 // 30)]},
        }
        plist = [p for p in plist if p["name"] != "Luna"]

    houses = None
    if has_time and req.lat is not None and req.lon is not None:
        cusps, ascmc = swe.houses(jd, req.lat, req.lon, house_bytes(req.house_system))
        houses = {
            "asc": round(ascmc[0], 4),
            "mc": round(ascmc[1], 4),
            "asc_sign": SIGNS[int(ascmc[0] // 30)],
            "cusps": [round(c, 4) for c in cusps],
            "system": req.house_system,
        }

    return {
        "date": req.date,
        "time": req.time if has_time else None,
        "time_quality": req.time_quality,
        "planets": plist,
        "moon_range": moon_range,
        # sin hora exacta NO hay casas ni Ascendente — el motor lo fuerza
        "houses": houses,
        "node": lunar_node(jd, req.node_type != "mean"),
    }


class RadixPoint(BaseModel):
    name: str
    lon: float


class TransitsReq(BaseModel):
    radix: list[RadixPoint]
    date: str
    time: Optional[str] = None
    orb_major: float = 3.0
    orb_minor: float = 1.5


@app.post("/transits")
def transits(req: TransitsReq) -> dict:
    jd = jd_from(req.date, req.time)
    trans = positions(jd)
    hits = []
    for t in trans:
        # aplicativo: la separación disminuye una hora después
        (lon_next, *_), _ = swe.calc_ut(jd + 1 / 24.0, PLANETS[t["name"]], FLAGS)
        for r in req.radix:
            for name, angle, major in ASPECTS:
                orb = req.orb_major if major else req.orb_minor
                delta = abs(sep(t["lon"], r.lon) - angle)
                if delta <= orb:
                    applying = abs(sep(lon_next, r.lon) - angle) < delta
                    hits.append({
                        "transit": t["name"], "radix": r.name, "aspect": name,
                        "orb": round(delta, 4), "applying": applying, "major": major,
                    })
    return {"date": req.date, "hits": sorted(hits, key=lambda h: h["orb"])}


def jd_to_iso(jd: float) -> str:
    y, m, d, h = swe.revjul(jd)
    hh = int(h)
    mm = int(round((h - hh) * 60))
    if mm == 60:
        hh, mm = hh + 1, 0
    return f"{y:04d}-{m:02d}-{d:02d}T{hh:02d}:{mm:02d}Z"


class SolarReturnReq(BaseModel):
    natal_date: str                       # YYYY-MM-DD
    natal_time: Optional[str] = None      # HH:MM (UTC)
    natal_time_quality: str = "exact"     # exact | approx | unknown
    year: int                             # año del retorno buscado
    lat: Optional[float] = None           # lugar donde se pasa la RS (para casas)
    lon: Optional[float] = None
    house_system: str = "placidus"


@app.post("/solar_return")
def solar_return(req: SolarReturnReq) -> dict:
    """Revolución solar: momento exacto en que el Sol vuelve a su longitud
    natal en el año pedido. Sin hora natal, el Sol natal tiene ~±0.5° de
    incertidumbre → el momento de la RS queda ±12h y se marca approximate
    (y NO se calculan casas, igual que en /chart)."""
    has_time = req.natal_time is not None and req.natal_time_quality != "unknown"
    jd_natal = jd_from(req.natal_date, req.natal_time if has_time else None)
    (natal_sun, *_), _ = swe.calc_ut(jd_natal, swe.SUN, FLAGS)

    _, m, d = (int(x) for x in req.natal_date.split("-"))
    jd = swe.julday(req.year, m, d, 12.0)
    for _ in range(30):  # Newton sobre la longitud solar (converge en ~4 pasos)
        (sun, _lat, _dist, speed, *_), _ = swe.calc_ut(jd, swe.SUN, FLAGS)
        delta = ((natal_sun - sun + 180.0) % 360.0) - 180.0
        if abs(delta) < 1e-7:
            break
        jd += delta / (speed if speed else 0.9856)

    plist = positions(jd)
    houses = None
    if has_time and req.lat is not None and req.lon is not None:
        cusps, ascmc = swe.houses(jd, req.lat, req.lon, house_bytes(req.house_system))
        houses = {
            "asc": round(ascmc[0], 4),
            "mc": round(ascmc[1], 4),
            "asc_sign": SIGNS[int(ascmc[0] // 30)],
            "cusps": [round(c, 4) for c in cusps],
            "system": req.house_system,
        }
    return {
        "year": req.year,
        "moment_utc": jd_to_iso(jd),
        "natal_sun_lon": round(natal_sun, 6),
        "approximate": not has_time,
        "planets": plist,
        "houses": houses,
    }


class ProgressionsReq(BaseModel):
    natal_date: str
    natal_time: Optional[str] = None
    natal_time_quality: str = "exact"
    target_date: str  # YYYY-MM-DD: a qué fecha de la vida se progresa


@app.post("/progressions")
def progressions(req: ProgressionsReq) -> dict:
    """Progresiones secundarias: 1 día después del nacimiento = 1 año de vida.
    Sin hora natal, la Luna progresada hereda la imprecisión (~±0.5° por las
    ±12h natales): se informa igual pero marcada moon_imprecise."""
    has_time = req.natal_time is not None and req.natal_time_quality != "unknown"
    jd_natal = jd_from(req.natal_date, req.natal_time if has_time else None)
    jd_target = jd_from(req.target_date, "12:00")
    years = (jd_target - jd_natal) / 365.2425
    jd_prog = jd_natal + years  # la clave del método: días como años
    return {
        "target_date": req.target_date,
        "years": round(years, 2),
        "progressed_moment_utc": jd_to_iso(jd_prog),
        "moon_imprecise": not has_time,
        "planets": positions(jd_prog),
    }


class LunarReturnReq(BaseModel):
    natal_date: str                    # YYYY-MM-DD (nacimiento)
    natal_time: Optional[str] = None   # HH:MM UTC si se conoce
    natal_time_quality: str = "exact"
    target_date: str                   # el retorno lunar VIGENTE a esta fecha
    lat: Optional[float] = None        # sede donde se reubica (casas/ASC)
    lon: Optional[float] = None
    house_system: str = "placidus"


@app.post("/lunar_return")
def lunar_return(req: LunarReturnReq) -> dict:
    """Revolución lunar: momento en que la Luna vuelve a su longitud natal,
    el último retorno ANTES de target_date. Sin hora natal, la Luna natal
    tiene ±6.5° de incertidumbre → el momento del retorno queda ±12h y el
    ASC reubicado pierde precisión: se marca approximate."""
    has_time = req.natal_time is not None and req.natal_time_quality != "unknown"
    jd_natal = jd_from(req.natal_date, req.natal_time if has_time else None)
    (natal_moon, *_), _ = swe.calc_ut(jd_natal, swe.MOON, FLAGS)

    jd = jd_from(req.target_date, "12:00")
    for _ in range(40):  # Newton sobre la longitud lunar (~13.2°/día)
        (moon, _lat, _dist, speed, *_), _ = swe.calc_ut(jd, swe.MOON, FLAGS)
        delta = ((natal_moon - moon + 180.0) % 360.0) - 180.0
        if abs(delta) < 1e-6:
            break
        jd += delta / (speed if speed else 13.176)
    if jd > jd_from(req.target_date, "23:59"):
        jd -= 27.321661  # mes sidéreo
        for _ in range(40):
            (moon, _lat, _dist, speed, *_), _ = swe.calc_ut(jd, swe.MOON, FLAGS)
            delta = ((natal_moon - moon + 180.0) % 360.0) - 180.0
            if abs(delta) < 1e-6:
                break
            jd += delta / (speed if speed else 13.176)

    plist = positions(jd)
    houses = None
    asc_moon_orb = None
    if req.lat is not None and req.lon is not None:
        cusps, ascmc = swe.houses(jd, req.lat, req.lon, house_bytes(req.house_system))
        houses = {
            "asc": round(ascmc[0], 4),
            "mc": round(ascmc[1], 4),
            "asc_sign": SIGNS[int(ascmc[0] // 30)],
            "cusps": [round(c, 4) for c in cusps],
            "system": req.house_system,
        }
        asc_moon_orb = round(sep(ascmc[0], natal_moon), 4)
    return {
        "moment_utc": jd_to_iso(jd),
        "natal_moon_lon": round(natal_moon, 6),
        "natal_moon_sign": SIGNS[int(natal_moon // 30)],
        "approximate": not has_time,
        "planets": plist,
        "houses": houses,
        "asc_moon_orb": asc_moon_orb,
    }


class CrossReq(BaseModel):
    a: list[RadixPoint]  # carta móvil (RS / progresada / evento / tránsitos)
    b: list[RadixPoint]  # carta base (natal)
    orb_major: float = 3.0
    orb_minor: float = 1.5


@app.post("/cross")
def cross(req: CrossReq) -> dict:
    """Aspectos entre dos juegos de posiciones (sinastría genérica): RS vs
    natal, progresada vs natal, o carta A vs carta B para sinastría real."""
    hits = []
    for pa in req.a:
        for pb in req.b:
            for name, angle, major in ASPECTS:
                orb = req.orb_major if major else req.orb_minor
                delta = abs(sep(pa.lon, pb.lon) - angle)
                if delta <= orb:
                    hits.append({
                        "a": pa.name, "b": pb.name, "aspect": name,
                        "orb": round(delta, 4), "major": major,
                    })
    return {"hits": sorted(hits, key=lambda h: h["orb"])}


# claves de dirección simbólica: grados de arco por año transcurrido.
# c60 (Progresiones Cósmicas / C-60 de W. Koch) es la misma técnica con
# clave=6.0 — mismo endpoint cubre ambas, ver plan F3.
DIRECTION_KEYS = {
    "ptolemy": 1.0,
    "naibod": 360.0 / 365.2425,
    "duodenary": 2.5,
    "pythagorean": 5.0,
    "c60": 6.0,
}


class SymbolicDirectionsReq(BaseModel):
    natal_date: str
    natal_time: Optional[str] = None
    natal_time_quality: str = "exact"
    target_date: str
    key: str = "ptolemy"
    lat: Optional[float] = None
    lon: Optional[float] = None
    house_system: str = "placidus"


@app.post("/symbolic_directions")
def symbolic_directions(req: SymbolicDirectionsReq) -> dict:
    """Direcciones simbólicas: arco uniforme = años transcurridos × clave,
    sumado a CADA punto natal (planetas y, si hay hora, ASC/MC/cúspides —
    se dirige la carta entera con el mismo arco, no solo los planetas)."""
    has_time = req.natal_time is not None and req.natal_time_quality != "unknown"
    jd_natal = jd_from(req.natal_date, req.natal_time if has_time else None)
    jd_target = jd_from(req.target_date, "12:00")
    years = (jd_target - jd_natal) / 365.2425
    key_value = DIRECTION_KEYS.get(req.key, DIRECTION_KEYS["ptolemy"])
    arc = years * key_value

    directed_planets = []
    for p in positions(jd_natal):
        dlon = (p["lon"] + arc) % 360.0
        directed_planets.append({
            "name": p["name"], "lon": round(dlon, 6), "sign": SIGNS[int(dlon // 30)],
            "sign_degree": round(dlon % 30, 4),
        })

    directed_houses = None
    if has_time and req.lat is not None and req.lon is not None:
        cusps, ascmc = swe.houses(jd_natal, req.lat, req.lon, house_bytes(req.house_system))
        d_asc = (ascmc[0] + arc) % 360.0
        d_mc = (ascmc[1] + arc) % 360.0
        directed_houses = {
            "asc": round(d_asc, 4),
            "mc": round(d_mc, 4),
            "asc_sign": SIGNS[int(d_asc // 30)],
            "cusps": [round((c + arc) % 360.0, 4) for c in cusps],
            "system": req.house_system,
        }

    return {
        "key": req.key,
        "arc_deg": round(arc, 6),
        "years": round(years, 4),
        "target_date": req.target_date,
        "planets": directed_planets,
        "houses": directed_houses,
    }


class ArabicPartsReq(BaseModel):
    natal_date: str
    natal_time: str  # requerido: sin hora no hay ASC, y la Fortuna lo necesita
    lat: float
    lon: float
    house_system: str = "placidus"


@app.post("/arabic_parts")
def arabic_parts(req: ArabicPartsReq) -> dict:
    """Parte de la Fortuna: ASC + Luna − Sol en carta DIURNA (Sol sobre el
    horizonte, casas 7-12); invertida (ASC + Sol − Luna) en carta NOCTURNA."""
    jd = jd_from(req.natal_date, req.natal_time)
    (sun, *_), _ = swe.calc_ut(jd, swe.SUN, FLAGS)
    (moon, *_), _ = swe.calc_ut(jd, swe.MOON, FLAGS)
    cusps, ascmc = swe.houses(jd, req.lat, req.lon, house_bytes(req.house_system))
    asc = ascmc[0]
    sun_house = house_of(sun, list(cusps))
    is_day = sun_house >= 7
    fortuna = (asc + moon - sun) % 360.0 if is_day else (asc + sun - moon) % 360.0
    return {
        "is_day": is_day,
        "sun_house": sun_house,
        "fortuna": {
            "lon": round(fortuna, 6),
            "sign": SIGNS[int(fortuna // 30)],
            "sign_degree": round(fortuna % 30, 4),
        },
    }


class MidpointsReq(BaseModel):
    points: list[RadixPoint]
    orb: float = 1.5


@app.post("/midpoints")
def midpoints(req: MidpointsReq) -> dict:
    """Puntos medios entre cada par + árbol de puntos medios estilo Ebertin
    (dial de 90°): qué otros puntos del mismo juego caen sobre el punto
    medio directo o cualquiera de sus resonancias de 90° (0/90/180/270°)."""
    pairs = []
    n = len(req.points)
    for i in range(n):
        for j in range(i + 1, n):
            a, b = req.points[i], req.points[j]
            near = ((a.lon + b.lon) / 2.0) % 360.0
            far = (near + 180.0) % 360.0
            hits = []
            for k, p in enumerate(req.points):
                if k == i or k == j:
                    continue
                diff = dial_diff(p.lon, near)
                if diff <= req.orb:
                    hits.append({"name": p.name, "orb": round(diff, 4)})
            pairs.append({
                "a": a.name, "b": b.name,
                "near": round(near, 4), "far": round(far, 4),
                "hits": sorted(hits, key=lambda h: h["orb"]),
            })
    return {"pairs": pairs}


class HarmonicReq(BaseModel):
    points: list[RadixPoint]
    harmonic: float


@app.post("/harmonic")
def harmonic(req: HarmonicReq) -> dict:
    """Carta armónica H: cada longitud natal ×H, reducida a 360°."""
    out = []
    for p in req.points:
        hlon = (p.lon * req.harmonic) % 360.0
        out.append({
            "name": p.name, "lon": round(hlon, 6), "sign": SIGNS[int(hlon // 30)],
            "sign_degree": round(hlon % 30, 4),
        })
    return {"harmonic": req.harmonic, "points": out}


class ArmcReq(BaseModel):
    date: str
    time: str  # requerido: ARMC/ascensional no existen sin hora exacta
    lat: float
    lon: float
    house_system: str = "placidus"


@app.post("/armc")
def armc_endpoint(req: ArmcReq) -> dict:
    """Base de la astrología ascensional/topocéntrica (Polich-Page): ARMC
    (ascmc[2] de swe.houses — tiempo sidéreo local en grados), ascensión
    recta (RA) y declinación de cada planeta MÁS Ascendente/Medio Cielo
    (convertidos de eclíptico a ecuatorial vía swe.cotrans con la
    obliquidad del momento — necesarios como promissor/significador en
    /primary_directions), diferencia ascensional AD = asin(tan(lat)·tan(dec))
    — CLAMPEADA a [-1,1] antes del asin (rompe fuera de rango en latitudes/
    declinaciones altas, caso circumpolar) — y ascensión oblicua OA = RA − AD."""
    jd = jd_from(req.date, req.time)
    _cusps, ascmc = swe.houses(jd, req.lat, req.lon, house_bytes(req.house_system))
    (obliquity, *_), _flag_obl = swe.calc_ut(jd, swe.ECL_NUT, FLAGS)
    lat_rad = math.radians(req.lat)

    def ad_oa(ra: float, dec: float) -> tuple[float, float]:
        tan_product = math.tan(lat_rad) * math.tan(math.radians(dec))
        ad = math.degrees(math.asin(max(-1.0, min(1.0, tan_product))))
        return ad, (ra - ad) % 360.0

    points = []
    for name, pid in PLANETS.items():
        (ra, dec, *_), _flag = swe.calc_ut(jd, pid, FLAGS | swe.FLG_EQUATORIAL)
        ad, oa = ad_oa(ra, dec)
        points.append({
            "name": name, "ra": round(ra, 6), "dec": round(dec, 6),
            "ad": round(ad, 6), "oa": round(oa, 6),
        })

    for label, ecl_lon in (("Ascendente", ascmc[0]), ("Medio Cielo", ascmc[1])):
        ra, dec, _dist = swe.cotrans((ecl_lon, 0.0, 1.0), -obliquity)
        ad, oa = ad_oa(ra, dec)
        points.append({
            "name": label, "ra": round(ra, 6), "dec": round(dec, 6),
            "ad": round(ad, 6), "oa": round(oa, 6),
        })

    return {
        "armc": round(ascmc[2], 6),
        "asc": round(ascmc[0], 4),
        "mc": round(ascmc[1], 4),
        "obliquity": round(obliquity, 6),
        "points": points,
    }


def _prop_dist(ra: float, dec: float, armc: float, lat: float) -> tuple[float, float, bool]:
    """Distancia proporcional (MD/SA) de un punto respecto al meridiano más
    cercano (MC si está sobre el horizonte, IC si no) — método semi-arco
    (Placidus). El lado diurno/nocturno se decide por la altitud REAL del
    punto (sin_alt = sen(lat)sen(dec) + cos(lat)cos(dec)cos(HA)), no por un
    umbral fijo de distancia meridiana — así no se confunde en cartas de
    declinación alta. Devuelve (proporción, semi-arco, es_diurno)."""
    lat_rad = math.radians(lat)
    dec_rad = math.radians(dec)
    ha = math.radians(armc - ra)
    sin_alt = math.sin(lat_rad) * math.sin(dec_rad) + math.cos(lat_rad) * math.cos(dec_rad) * math.cos(ha)
    diurnal = sin_alt > 0
    ad = math.degrees(math.asin(max(-1.0, min(1.0, math.tan(lat_rad) * math.tan(dec_rad)))))
    sa = 90.0 + ad if diurnal else 90.0 - ad
    reference = armc if diurnal else (armc + 180.0) % 360.0
    md = ((ra - reference + 180.0) % 360.0) - 180.0
    return (md / sa if sa else 0.0), sa, diurnal


# medida de tiempo: cuántos grados de arco equivalen a 1 año (misma idea que
# DIRECTION_KEYS de /symbolic_directions, subconjunto relevante acá)
PRIMARY_TIME_KEYS = {"ptolemy": 1.0, "naibod": 360.0 / 365.2425}


class PrimaryDirectionPoint(BaseModel):
    name: str
    ra: float
    dec: float


class PrimaryDirectionsReq(BaseModel):
    armc: float          # ARMC natal (de /armc)
    lat: float            # latitud natal
    promissor: PrimaryDirectionPoint
    significator: PrimaryDirectionPoint
    key: str = "ptolemy"  # ptolemy=1°/año, naibod=0.9856°/año


@app.post("/primary_directions")
def primary_directions(req: PrimaryDirectionsReq) -> dict:
    """Dirección primaria por ARCO SEMI-DIURNO (método Placidus, EN MUNDO,
    directa): el promissor avanza con la rotación diurna hasta ocupar la
    misma posición proporcional (MD/SA) que el significador tiene en su
    propia carta natal.
    Arco = (PropDist_promissor − PropDist_significador) × SA_promissor —
    fórmula estándar del método semi-arco unificado (verificada contra
    fuente externa independiente, ver comentario en el módulo de tests).
    Convertido a años con la clave elegida (misma tasa Naibod que
    /symbolic_directions).
    ADVERTENCIA: de las técnicas de este archivo, es la de MÁS convenciones
    alternativas posibles en la tradición (en mundo vs en zodíaco, directa
    vs conversa, Placidus vs Regiomontanus) — cruzar contra una segunda
    fuente antes de usarla en una consulta real con un cliente."""
    prop_p, sa_p, diurnal_p = _prop_dist(req.promissor.ra, req.promissor.dec, req.armc, req.lat)
    prop_s, _sa_s, diurnal_s = _prop_dist(req.significator.ra, req.significator.dec, req.armc, req.lat)
    arc = (prop_p - prop_s) * sa_p
    key_value = PRIMARY_TIME_KEYS.get(req.key, PRIMARY_TIME_KEYS["ptolemy"])
    return {
        "arc_deg": round(arc, 6),
        "years": round(arc / key_value, 4),
        "key": req.key,
        "promissor_prop_dist": round(prop_p, 6),
        "significator_prop_dist": round(prop_s, 6),
        "promissor_diurnal": diurnal_p,
        "significator_diurnal": diurnal_s,
    }


CLASSICAL_SEVEN = ["Sol", "Luna", "Mercurio", "Venus", "Marte", "Júpiter", "Saturno"]
ANGLES = ["Ascendente", "Medio Cielo", "Descendente", "Fondo del Cielo"]


def _direction_points(jd: float, lat: float, lon: float, house_system: str) -> tuple[float, dict[str, tuple[float, float]]]:
    """ARMC + {nombre: (ra, dec)} de los 7 clásicos y los 4 ángulos en un jd
    dado — el núcleo reusado tanto por /armc (un solo momento) como por
    /rectify (cientos de momentos candidatos, de ahí separarlo)."""
    _cusps, ascmc = swe.houses(jd, lat, lon, house_bytes(house_system))
    (obliquity, *_), _flag_obl = swe.calc_ut(jd, swe.ECL_NUT, FLAGS)
    points: dict[str, tuple[float, float]] = {}
    for name in CLASSICAL_SEVEN:
        (ra, dec, *_), _flag = swe.calc_ut(jd, PLANETS[name], FLAGS | swe.FLG_EQUATORIAL)
        points[name] = (ra, dec)
    for label, ecl_lon in (
        ("Ascendente", ascmc[0]), ("Medio Cielo", ascmc[1]),
        ("Descendente", (ascmc[0] + 180.0) % 360.0), ("Fondo del Cielo", (ascmc[1] + 180.0) % 360.0),
    ):
        ra, dec, _dist = swe.cotrans((ecl_lon, 0.0, 1.0), -obliquity)
        points[label] = (ra, dec)
    return ascmc[2], points


class RectifyEvent(BaseModel):
    date: str
    label: Optional[str] = None


class RectifyReq(BaseModel):
    natal_date: str
    lat: float
    lon: float
    time_from: str = "00:00"
    time_to: str = "23:59"
    step_minutes: int = 2
    house_system: str = "placidus"
    key: str = "ptolemy"
    orb_years: float = 0.5
    events: list[RectifyEvent]


@app.post("/rectify")
def rectify(req: RectifyReq) -> dict:
    """Rectificación automática del Ascendente por direcciones primarias a
    eventos de vida: para cada hora candidata dentro de la ventana horaria
    incierta, prueba si algún clásico (Sol..Saturno) dirigido a algún ángulo
    (ASC/MC/DSC/FC) por arco semi-diurno (misma fórmula de /primary_directions)
    cae en años ≈ la edad real en cada evento cargado, dentro del orbe. Cada
    candidata se puntúa por cuántos eventos explica — NO reemplaza el juicio
    del astrólogo: devuelve varias candidatas rankeadas con el detalle de qué
    dirección las explica, para revisar, no una única respuesta ciega.
    Misma advertencia de convenciones que /primary_directions (en mundo,
    Placidus, directa) — cruzar con una segunda fuente antes de usar en una
    consulta real."""
    if not req.events:
        raise HTTPException(400, "Cargá al menos un evento para rectificar.")

    key_value = PRIMARY_TIME_KEYS.get(req.key, PRIMARY_TIME_KEYS["ptolemy"])
    jd_birth_date = jd_from(req.natal_date, "00:00")
    events: list[tuple[str, Optional[str], float]] = []
    for ev in req.events:
        jd_event = jd_from(ev.date, "00:00")
        age_years = (jd_event - jd_birth_date) / 365.2425
        if age_years <= 0:
            raise HTTPException(400, f"El evento {ev.date} no puede ser anterior o igual al nacimiento.")
        events.append((ev.date, ev.label, age_years))

    jd_window_start = jd_from(req.natal_date, req.time_from)
    jd_window_end = jd_from(req.natal_date, req.time_to)
    if jd_window_end < jd_window_start:
        jd_window_end += 1.0  # ventana cruza medianoche (ej. 23:00 a 01:00)
    step = req.step_minutes / (24.0 * 60.0)

    candidates = []
    jd = jd_window_start
    while jd <= jd_window_end + 1e-9:
        armc, points = _direction_points(jd, req.lat, req.lon, req.house_system)
        matches = []
        for ev_date, ev_label, age_years in events:
            best = None
            for promissor_name in CLASSICAL_SEVEN:
                pra, pdec = points[promissor_name]
                prop_p, sa_p, _diurnal = _prop_dist(pra, pdec, armc, req.lat)
                for angle_name in ANGLES:
                    ara, adec = points[angle_name]
                    prop_a, _sa_a, _diurnal_a = _prop_dist(ara, adec, armc, req.lat)
                    arc = (prop_p - prop_a) * sa_p
                    years = arc / key_value
                    error = abs(years - age_years)
                    if best is None or error < best["error_years"]:
                        best = {
                            "event_date": ev_date, "event_label": ev_label,
                            "promissor": promissor_name, "angle": angle_name,
                            "arc_years": round(years, 3), "error_years": round(error, 3),
                        }
            if best is not None and best["error_years"] <= req.orb_years:
                matches.append(best)
        if matches:
            _y, _m, _d, h = swe.revjul(jd)
            hh = int(h)
            mm = int(round((h - hh) * 60))
            if mm == 60:
                mm = 0
                hh += 1
            candidates.append({
                "time": f"{hh:02d}:{mm:02d}",
                "score": len(matches),
                "total_error_years": round(sum(m["error_years"] for m in matches), 3),
                "matches": matches,
            })
        jd += step

    candidates.sort(key=lambda c: (-c["score"], c["total_error_years"]))
    return {"events_count": len(events), "candidates": candidates[:15]}


# Dignidades esenciales — astrología tradicional/medieval, tabla de Lilly
# (Christian Astrology, 1647), la misma que usa la mayoría del software
# tradicional moderno (Astro Gold, Delphic Oracle). Solo los 7 clásicos:
# la dignidad esencial es un sistema anterior al descubrimiento de los
# planetas exteriores, que no tienen domicilio/exaltación en esta tradición.
CLASSICAL_SEVEN_ORDERED = ["Saturno", "Júpiter", "Marte", "Sol", "Venus", "Mercurio", "Luna"]

# sign_index (0=Aries..11=Piscis) → planeta regente del domicilio
DOMICILE = {
    0: "Marte", 1: "Venus", 2: "Mercurio", 3: "Luna", 4: "Sol", 5: "Mercurio",
    6: "Venus", 7: "Marte", 8: "Júpiter", 9: "Saturno", 10: "Saturno", 11: "Júpiter",
}

# sign_index → (planeta exaltado, grado exacto de exaltación dentro del signo)
EXALTATION = {
    0: ("Sol", 19.0), 1: ("Luna", 3.0), 3: ("Júpiter", 15.0), 5: ("Mercurio", 15.0),
    6: ("Saturno", 21.0), 9: ("Marte", 28.0), 11: ("Venus", 27.0),
}

# triplicidad por elemento (día/noche/participante) — tabla de Lilly
TRIPLICITY_BY_ELEMENT = {
    "Fuego": {"day": "Sol", "night": "Júpiter", "participating": "Saturno"},
    "Tierra": {"day": "Venus", "night": "Luna", "participating": "Marte"},
    "Aire": {"day": "Saturno", "night": "Mercurio", "participating": "Júpiter"},
    "Agua": {"day": "Venus", "night": "Marte", "participating": "Luna"},
}
ELEMENT_BY_SIGN_MOD = {0: "Fuego", 1: "Tierra", 2: "Aire", 3: "Agua"}

# términos/límites egipcios (0-30° dentro de cada signo) — la tabla estándar
# citada por Ptolomeo y reproducida por Lilly, la más usada en software
# tradicional actual. Cada tupla: (planeta, grado_inicio, grado_fin).
EGYPTIAN_TERMS: dict[int, list[tuple[str, float, float]]] = {
    0: [("Júpiter", 0, 6), ("Venus", 6, 12), ("Mercurio", 12, 20), ("Marte", 20, 25), ("Saturno", 25, 30)],
    1: [("Venus", 0, 8), ("Mercurio", 8, 14), ("Júpiter", 14, 22), ("Saturno", 22, 27), ("Marte", 27, 30)],
    2: [("Mercurio", 0, 6), ("Júpiter", 6, 12), ("Venus", 12, 17), ("Marte", 17, 24), ("Saturno", 24, 30)],
    3: [("Marte", 0, 7), ("Venus", 7, 13), ("Mercurio", 13, 19), ("Júpiter", 19, 26), ("Saturno", 26, 30)],
    4: [("Júpiter", 0, 6), ("Venus", 6, 11), ("Saturno", 11, 18), ("Mercurio", 18, 24), ("Marte", 24, 30)],
    5: [("Mercurio", 0, 7), ("Venus", 7, 17), ("Júpiter", 17, 21), ("Marte", 21, 28), ("Saturno", 28, 30)],
    6: [("Saturno", 0, 6), ("Mercurio", 6, 14), ("Júpiter", 14, 21), ("Venus", 21, 28), ("Marte", 28, 30)],
    7: [("Marte", 0, 7), ("Venus", 7, 11), ("Mercurio", 11, 19), ("Júpiter", 19, 24), ("Saturno", 24, 30)],
    8: [("Júpiter", 0, 12), ("Venus", 12, 17), ("Mercurio", 17, 21), ("Saturno", 21, 26), ("Marte", 26, 30)],
    9: [("Mercurio", 0, 7), ("Júpiter", 7, 14), ("Venus", 14, 22), ("Saturno", 22, 26), ("Marte", 26, 30)],
    10: [("Mercurio", 0, 7), ("Venus", 7, 13), ("Júpiter", 13, 20), ("Marte", 20, 25), ("Saturno", 25, 30)],
    11: [("Venus", 0, 12), ("Júpiter", 12, 16), ("Mercurio", 16, 19), ("Marte", 19, 28), ("Saturno", 28, 30)],
}

# rostros/decanatos — orden caldeo (Saturno→Júpiter→Marte→Sol→Venus→Mercurio→
# Luna, velocidad orbital aparente decreciente) recorrido sin cortes por los
# 36 decanatos del zodíaco, empezando por Marte en Aries 0° (punto de partida
# tradicional). Se deriva por índice en vez de tabla — 36 entradas a mano es
# demasiado propenso a error de transcripción.
_CHALDEAN_FROM_ARIES = ["Marte", "Sol", "Venus", "Mercurio", "Luna", "Saturno", "Júpiter"]


def _face_ruler(sign_index: int, decan_in_sign: int) -> str:
    return _CHALDEAN_FROM_ARIES[(sign_index * 3 + decan_in_sign) % 7]


DIGNITY_SCORE = {"domicile": 5, "exaltation": 4, "triplicity": 3, "term": 2, "face": 1}
DEBILITY_SCORE = {"detriment": -5, "fall": -4}


def _dignities_at(lon: float, is_day: bool) -> dict:
    """Tabla completa de dignidades esenciales en una longitud eclíptica:
    domicilio/exaltación/detrimento/caída/triplicidad/término/rostro, más el
    puntaje de cada uno de los 7 clásicos en ese grado (para el almutem)."""
    norm = lon % 360.0
    sign_index = int(norm // 30)
    degree_in_sign = norm % 30.0
    opposite_sign = (sign_index + 6) % 12

    domicile_ruler = DOMICILE[sign_index]
    detriment_ruler = DOMICILE[opposite_sign]
    exalt_planet, exalt_degree = EXALTATION.get(sign_index, (None, None))
    fall_planet, _fall_degree = EXALTATION.get(opposite_sign, (None, None))

    element = ELEMENT_BY_SIGN_MOD[sign_index % 4]
    triplicity = TRIPLICITY_BY_ELEMENT[element]
    triplicity_ruler = triplicity["day"] if is_day else triplicity["night"]

    term_ruler = next(p for p, lo, hi in EGYPTIAN_TERMS[sign_index] if lo <= degree_in_sign < hi)
    decan_in_sign = int(degree_in_sign // 10)
    face_ruler = _face_ruler(sign_index, decan_in_sign)

    scores = {p: 0 for p in CLASSICAL_SEVEN_ORDERED}
    scores[domicile_ruler] += DIGNITY_SCORE["domicile"]
    if exalt_planet:
        scores[exalt_planet] += DIGNITY_SCORE["exaltation"]
    scores[triplicity_ruler] += DIGNITY_SCORE["triplicity"]
    scores[term_ruler] += DIGNITY_SCORE["term"]
    scores[face_ruler] += DIGNITY_SCORE["face"]
    almuten = max(scores.items(), key=lambda kv: kv[1])

    return {
        "sign": SIGNS[sign_index], "sign_degree": round(degree_in_sign, 4),
        "domicile_ruler": domicile_ruler,
        "exaltation_ruler": exalt_planet, "exaltation_degree": exalt_degree,
        "detriment_ruler": detriment_ruler,
        "fall_ruler": fall_planet,
        "triplicity_day_ruler": triplicity["day"], "triplicity_night_ruler": triplicity["night"],
        "triplicity_participating_ruler": triplicity["participating"], "triplicity_ruler": triplicity_ruler,
        "term_ruler": term_ruler,
        "face_ruler": face_ruler,
        "scores": scores,
        "almuten": almuten[0], "almuten_score": almuten[1],
    }


class DignitiesPoint(BaseModel):
    name: str
    lon: float


class DignitiesReq(BaseModel):
    points: list[DignitiesPoint]
    is_day: bool


@app.post("/dignities")
def dignities(req: DignitiesReq) -> dict:
    """Dignidades esenciales tradicionales (domicilio, exaltación, detrimento,
    caída, triplicidad, término egipcio, rostro caldeo) para cada punto
    pedido, más el Almutem Figuris (Lilly: domicilio=5, exaltación=4,
    triplicidad=3, término=2, rostro=1 — el clásico con más puntos en ese
    grado exacto, sin importar qué haya ahí en realidad). Si el propio punto
    ES uno de los 7 clásicos, se marca si está dignificado/debilitado en su
    propia posición (útil para ver de un vistazo qué planetas natales están
    fuertes o débiles).
    ADVERTENCIA: la triplicidad y los términos tienen más de una tabla
    tradicional posible (Ptolomeo vs Dorotheus vs Lilly para triplicidad;
    egipcios vs Ptolemaicos para términos) — esta usa la tabla de Lilly/
    términos egipcios, la más difundida en software tradicional actual,
    pero cruzar con una segunda fuente antes de usar en una consulta real."""
    out = []
    for p in req.points:
        d = _dignities_at(p.lon, req.is_day)
        is_classical = p.name in CLASSICAL_SEVEN_ORDERED
        own_score = None
        dignified_as = []
        debilitated_as = []
        if is_classical:
            own_score = d["scores"][p.name]
            if d["domicile_ruler"] == p.name:
                dignified_as.append("domicilio")
            if d["exaltation_ruler"] == p.name:
                dignified_as.append("exaltación")
            if d["triplicity_ruler"] == p.name:
                dignified_as.append("triplicidad")
            if d["term_ruler"] == p.name:
                dignified_as.append("término")
            if d["face_ruler"] == p.name:
                dignified_as.append("rostro")
            if d["detriment_ruler"] == p.name:
                debilitated_as.append("detrimento")
                own_score += DEBILITY_SCORE["detriment"]
            if d["fall_ruler"] == p.name:
                debilitated_as.append("caída")
                own_score += DEBILITY_SCORE["fall"]
        out.append({
            "name": p.name, **d,
            "own_score": own_score, "dignified_as": dignified_as, "debilitated_as": debilitated_as,
        })
    return {"points": out}


def _norm_lon(x: float) -> float:
    """normaliza una longitud geográfica a (-180, 180]."""
    return ((x + 180.0) % 360.0) - 180.0


class AstrocartographyReq(BaseModel):
    date: str
    time: str  # requerido: astrocartografía necesita el momento exacto (UTC)
    points: Optional[list[str]] = None  # nombres de planetas; default = los 10 clásicos
    lat_step: float = 2.0  # muestreo de latitud (grados) para las curvas ASC/DESC


@app.post("/astrocartography")
def astrocartography(req: AstrocartographyReq) -> dict:
    """Astrocartografía: para cada planeta, las líneas MC/IC (verticales,
    longitud geográfica constante) y ASC/DESC (curvas, longitud en función
    de la latitud) donde ese planeta cae exactamente angular (culminando o
    naciendo/poniendo) al momento del evento.

    MC/IC: fórmula directa. LST = ARMC en grados = GST + longitud_geográfica
    (identidad ya verificada: swe.sidtime(jd)*15 == swe.houses(jd,*,lon=0)[1][2][2]).
    En el MC el ángulo horario HA=0 → LST=RA → longitud_MC = RA − GST. El IC
    es el meridiano opuesto: longitud_IC = longitud_MC + 180°.

    ASC/DESC: NO hace falta bisección numérica (a diferencia de lo que
    suponía el plan original) — es la MISMA identidad de orto/ocaso que ya
    usan /armc y /primary_directions: el ángulo horario de orto/ocaso
    H0 = 90° + AD, con AD = asin(tan(lat)·tan(dec)), o de forma equivalente
    cos(H0) = −tan(lat)·tan(dec) (fórmula estándar de esfera celeste, la
    misma que se usa para la duración del día). El ASC ocurre en HA=−H0
    (antes de culminar, lado este), el DESC en HA=+H0 (lado oeste). Fuera
    de |tan(lat)·tan(dec)| ≥ 1 el punto es circumpolar en esa latitud para
    esa declinación — no nace/se pone, se omite esa muestra."""
    jd = jd_from(req.date, req.time)
    gst_deg = swe.sidtime(jd) * 15.0  # swe.sidtime da HORAS; ×15 = grados

    names = req.points or list(PLANETS.keys())
    lines = []
    for name in names:
        (ra, dec, *_), _flag = swe.calc_ut(jd, PLANETS[name], FLAGS | swe.FLG_EQUATORIAL)

        mc_lon = _norm_lon(ra - gst_deg)
        ic_lon = _norm_lon(mc_lon + 180.0)

        asc_points, desc_points = [], []
        lat = -66.0
        while lat <= 66.0 + 1e-9:
            tan_product = math.tan(math.radians(lat)) * math.tan(math.radians(dec))
            if abs(tan_product) < 1.0:
                h0 = math.degrees(math.acos(max(-1.0, min(1.0, -tan_product))))
                asc_points.append({"lat": round(lat, 4), "lon": round(_norm_lon(ra - h0 - gst_deg), 4)})
                desc_points.append({"lat": round(lat, 4), "lon": round(_norm_lon(ra + h0 - gst_deg), 4)})
            lat += req.lat_step

        lines.append({
            "name": name, "mc_lon": round(mc_lon, 4), "ic_lon": round(ic_lon, 4),
            "asc": asc_points, "desc": desc_points,
        })

    return {"date": req.date, "time": req.time, "gst_deg": round(gst_deg, 6), "lines": lines}


class FixedStarsReq(BaseModel):
    date: str
    time: str
    names: list[str]


@app.post("/fixed_stars")
def fixed_stars(req: FixedStarsReq) -> dict:
    """Posición de estrellas fijas nombradas (nombre tradicional del
    catálogo sefstars.txt: 'Regulus', 'Spica', 'Aldebaran', etc.) — ÚNICO
    endpoint del sidecar con archivo externo, ver _ephe_path arriba."""
    jd = jd_from(req.date, req.time)
    out = []
    for name in req.names:
        (lon, _lat_ecl, _dist, *_), resolved, _flag = swe.fixstar2_ut(name, jd, FLAGS)
        out.append({
            "name": name, "resolved_name": resolved,
            "lon": round(lon, 6), "sign": SIGNS[int(lon // 30)],
            "sign_degree": round(lon % 30, 4),
        })
    return {"stars": out}


class EclipsesReq(BaseModel):
    date: str
    time: Optional[str] = None


def _jd_to_iso(jd: float) -> dict:
    y, m, d, h = swe.revjul(jd)
    hh = int(h)
    mm = int(round((h - hh) * 60))
    if mm == 60:
        mm = 0
        hh += 1
    return {"date": f"{y:04d}-{m:02d}-{d:02d}", "time": f"{hh:02d}:{mm:02d}"}


def _moon_sun_diff(jd: float) -> float:
    (sun_lon, *_), _ = swe.calc_ut(jd, swe.SUN, FLAGS)
    (moon_lon, *_), _ = swe.calc_ut(jd, swe.MOON, FLAGS)
    return (moon_lon - sun_lon) % 360.0


def _find_lunation(jd_start: float, target_deg: float) -> float:
    """Novilunio (target=0) o plenilunio (target=180) más próximo hacia
    adelante desde jd_start — bisección sobre la diferencia Luna-Sol, un
    ciclo sinódico (~29.5 días) siempre cae dentro de la ventana de 40."""
    def f(jd: float) -> float:
        return ((_moon_sun_diff(jd) - target_deg + 180.0) % 360.0) - 180.0

    step = 1.0
    jd = jd_start
    prev = f(jd)
    for _ in range(40):
        nxt_jd = jd + step
        nxt = f(nxt_jd)
        sign_changed = (prev <= 0 < nxt) or (prev >= 0 > nxt)
        # un salto grande entre pasos es el wraparound de ±180° de f, no una
        # raíz real — sin este filtro, el salto se confundía con un cruce
        # legítimo y devolvía la misma fecha para target=0 y target=180.
        smooth = abs(nxt - prev) < 180.0
        if sign_changed and smooth:
            lo, hi, flo = jd, nxt_jd, prev
            for _ in range(40):
                mid = (lo + hi) / 2.0
                fmid = f(mid)
                if (flo <= 0) == (fmid <= 0):
                    lo, flo = mid, fmid
                else:
                    hi = mid
            return (lo + hi) / 2.0
        jd, prev = nxt_jd, nxt
    raise RuntimeError("no se encontró la lunación en la ventana de 40 días")


def _eclipse_type(retflag: int, kind: str) -> str:
    if kind == "solar":
        if retflag & swe.ECL_TOTAL:
            return "total"
        if retflag & swe.ECL_ANNULAR_TOTAL:
            return "híbrido (anular-total)"
        if retflag & swe.ECL_ANNULAR:
            return "anular"
        if retflag & swe.ECL_PARTIAL:
            return "parcial"
        return "desconocido"
    if retflag & swe.ECL_TOTAL:
        return "total"
    if retflag & swe.ECL_PARTIAL:
        return "parcial"
    if retflag & swe.ECL_PENUMBRAL:
        return "penumbral"
    return "desconocido"


@app.post("/eclipses_and_lunations")
def eclipses_and_lunations(req: EclipsesReq) -> dict:
    """Próxima luna nueva/llena y próximo eclipse solar/lunar hacia adelante
    desde la fecha dada. Los eclipses son GLOBALES (cuándo ocurren en el
    planeta) — no filtrados por si se ven desde un lugar puntual."""
    jd = jd_from(req.date, req.time)

    jd_new = _find_lunation(jd, 0.0)
    jd_full = _find_lunation(jd, 180.0)
    sol_flag, sol_tret = swe.sol_eclipse_when_glob(jd, FLAGS, 0, False)
    lun_flag, lun_tret = swe.lun_eclipse_when(jd, FLAGS, 0, False)

    return {
        "next_new_moon": _jd_to_iso(jd_new),
        "next_full_moon": _jd_to_iso(jd_full),
        "next_solar_eclipse": {**_jd_to_iso(sol_tret[0]), "type": _eclipse_type(sol_flag, "solar")},
        "next_lunar_eclipse": {**_jd_to_iso(lun_tret[0]), "type": _eclipse_type(lun_flag, "lunar")},
    }
