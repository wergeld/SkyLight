from __future__ import annotations

import math
import re
import unicodedata
from datetime import date, datetime, time
from pathlib import Path
from typing import Any


def normalize_target_key(name: Any) -> str:
    text = "" if name is None else str(name)
    text = unicodedata.normalize("NFKD", text).casefold()
    text = re.sub(r"[^a-z0-9+ ]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def target_slug(name: Any, max_length: int = 24) -> str:
    key = normalize_target_key(name)
    slug = re.sub(r"[^a-z0-9]+", "-", key).strip("-")
    return (slug or "target")[:max_length]


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    return str(value).strip()


def is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    if isinstance(value, (datetime, date, time)):
        return False
    return clean_text(value) == ""


def parse_float(value: Any) -> float | None:
    if is_blank(value):
        return None
    text = clean_text(value).replace(",", "")
    try:
        number = float(text)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def parse_int(value: Any) -> int | None:
    number = parse_float(value)
    if number is None:
        return None
    try:
        return int(round(number))
    except (TypeError, ValueError, OverflowError):
        return None


def parse_bool(value: Any) -> bool | None:
    if is_blank(value):
        return None
    if isinstance(value, bool):
        return value
    text = clean_text(value).casefold()
    if text in {"true", "t", "yes", "y", "1", "processed"}:
        return True
    if text in {"false", "f", "no", "n", "0", "unprocessed", "pending"}:
        return False
    return None


def parse_seconds(value: Any) -> float | None:
    if is_blank(value):
        return None
    match = re.search(r"[-+]?\d*\.?\d+", clean_text(value))
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, time):
        return value.strftime("%H:%M:%S")
    return str(value).strip()


def safe_filename(name: str, fallback: str = "upload.csv") -> str:
    base = Path(str(name or fallback)).name
    base = re.sub(r"[^A-Za-z0-9._ -]+", "_", base).strip(" ._")
    return base or fallback


def short_filename(name: str, max_length: int = 36) -> str:
    name = Path(str(name or "")).name
    if len(name) <= max_length:
        return name
    stem = Path(name).stem
    suffix = Path(name).suffix
    keep = max(6, max_length - len(suffix) - 1)
    return f"{stem[:keep]}…{suffix}"
