from __future__ import annotations

from urllib.parse import quote_plus

from . import database
from .text import normalize_target_key


def _generic_templates(target_name: str) -> list[dict[str, str]]:
    name = quote_plus(target_name)
    return [
        {
            "label": "AAVSO VSX search",
            "url": "https://vsx.aavso.org/index.php?view=search.top",
            "category": "Catalog",
            "notes": "Search the AAVSO International Variable Star Index.",
        },
        {
            "label": "AAVSO Light Curve Generator",
            "url": "https://www.aavso.org/LCGv2/",
            "category": "AAVSO",
            "notes": "Compare against historical AAVSO observations.",
        },
        {
            "label": "SIMBAD identifier query",
            "url": f"https://simbad.cds.unistra.fr/simbad/sim-id?Ident={name}",
            "category": "Catalog",
            "notes": "Coordinates, identifiers, spectral type, and bibliography.",
        },
        {
            "label": "VizieR VSX catalog",
            "url": f"https://vizier.cds.unistra.fr/viz-bin/VizieR?-source=B%2Fvsx&VSXName={name}",
            "category": "Catalog",
            "notes": "Query the VSX catalog through VizieR.",
        },
        {
            "label": "AAVSO finder chart (VSP)",
            "url": f"https://apps.aavso.org/vsp/chart/?star={name}",
            "category": "AAVSO",
            "notes": "Generate a finder chart with comparison stars.",
        },
        {
            "label": "AAVSO photometry search",
            "url": "https://apps.aavso.org/v2/data/search/photometry/",
            "category": "AAVSO",
            "notes": "Search and download AAVSO photometric observations.",
        },
        {
            "label": "AAVSO Target Tool",
            "url": "https://targettool.aavso.org/",
            "category": "AAVSO",
            "notes": "Check target visibility and observing priorities.",
        },
    ]


def ensure_default_resources() -> None:
    catalog = database.get_catalog()
    for _, row in catalog.iterrows():
        target_name = str(row["target_name"])
        target_key = str(row["target_key"])
        for item in _generic_templates(target_name):
            database.upsert_resource(
                {
                    **item,
                    "target_key": target_key,
                    "source": "StarLight defaults",
                }
            )


def get_target_resources(target_name: str, target_key: str | None = None) -> list[dict[str, str]]:
    canonical = database.resolve_alias_key(target_key or normalize_target_key(target_name))
    stored = database.get_resources(canonical)
    output: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in stored:
        key = (str(item.get("label", "")), str(item.get("url", "")))
        if key in seen or not key[1]:
            continue
        seen.add(key)
        output.append(
            {
                "label": str(item.get("label", "")),
                "url": str(item.get("url", "")),
                "category": str(item.get("category", "")),
                "notes": str(item.get("notes", "")),
                "source": str(item.get("source", "")),
            }
        )
    for item in _generic_templates(target_name):
        key = (item["label"], item["url"])
        if key not in seen:
            output.append({**item, "source": "StarLight default"})
            seen.add(key)
    return output


def target_metadata(target_name: str, target_key: str | None = None) -> dict:
    canonical = database.resolve_alias_key(target_key or normalize_target_key(target_name))
    catalog = database.get_catalog_target(canonical)
    if catalog:
        catalog["target_name"] = catalog["target_name"] or target_name
        return catalog
    return {
        "target_key": canonical,
        "target_name": target_name,
        "common_designation": "",
        "variable_type": "",
        "constellation": "",
        "brightness_range": "",
        "period_days": None,
        "epoch_jd": None,
        "period_timescale": "",
        "notes": "",
    }
