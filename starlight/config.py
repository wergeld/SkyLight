from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "StarLight"
APP_SUBTITLE = "Seestar Observation & Variable Star Logbook"
APP_VERSION = "1.0.0"

BASE_DIR = Path(__file__).resolve().parent.parent

DATA_DIR = Path(os.environ.get("STARLIGHT_DATA_DIR", BASE_DIR / "data"))
DB_PATH = DATA_DIR / "starlight.db"
UPLOADS_DIR = DATA_DIR / "uploads"

WORKBOOK_NAME = "Tampa_Variable_Star_Observing_Logbook.xlsx"
WORKBOOK_PATH = Path(os.environ.get("STARLIGHT_WORKBOOK_PATH", BASE_DIR / WORKBOOK_NAME))
SAMPLE_CSV_GLOB = "Magnitude_*.csv"

DEFAULT_SNR_MIN = 10.0
DEFAULT_MAG_ERR_MAX = 0.20
DEFAULT_SPIKE_SIGMA = 5.0
DEFAULT_SPIKE_MIN_DELTA = 0.15
SPIKE_WINDOW_POINTS = 7

TIME_STANDARD = "Local (Seestar EXP start)"
JD_ORIGIN_UNIX = 2440587.5

CATALOG_PERIOD_DAYS = {
    "dy pegasi": 105.0 / 1440.0,
    "algol": 2.867,
    "delta cephei": 5.366,
    "mira omicron ceti": 332.0,
    "r trianguli": 225.0,
    "r andromedae": 409.0,
    "betelgeuse": None,
    "ss cygni": 7.3,
}

CATALOG_ALIASES = {
    "dy pegasi": ["DY Peg"],
    "algol": ["Beta Persei"],
    "delta cephei": ["Delta Cep"],
    "mira omicron ceti": ["Mira", "Omicron Ceti"],
    "r trianguli": ["R Tri"],
    "r andromedae": ["R And"],
    "betelgeuse": ["Alpha Orionis"],
    "ss cygni": ["SS Cyg"],
}

GENERIC_RESOURCE_LABELS = {
    "vsx",
    "light_curve",
    "simbad",
    "vizier",
    "vsp",
    "aavso_data",
    "target_tool",
}


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
