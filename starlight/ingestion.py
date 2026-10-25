from __future__ import annotations

import hashlib
import io
import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from . import config, database
from .text import (
    clean_text,
    normalize_target_key,
    parse_bool,
    parse_float,
    parse_int,
    parse_seconds,
    safe_filename,
    stringify,
)


class IngestionError(ValueError):
    """Raised when a CSV cannot be interpreted as a Seestar export."""


REQUIRED_CANONICAL = ["Name", "Mag(obs)", "Mag(err)", "EXP start(JD)", "SNR"]

COLUMN_ALIASES = {
    "name": "Name",
    "target": "Name",
    "mag(obs)": "Mag(obs)",
    "mag_obs": "Mag(obs)",
    "magnitude": "Mag(obs)",
    "mag(err)": "Mag(err)",
    "mag_err": "Mag(err)",
    "magerr": "Mag(err)",
    "exp start(jd)": "EXP start(JD)",
    "exp_start(jd)": "EXP start(JD)",
    "jd": "EXP start(JD)",
    "jd_start": "EXP start(JD)",
    "snr": "SNR",
    "type": "Type",
    "ra": "RA",
    "dec": "DEC",
    "valid reference stars": "Valid Reference Stars",
    "reference magnitude": "Reference magnitude",
    "exp": "EXP",
    "exp start": "EXP start",
    "exp start(mjd)": "EXP start(MJD)",
    "exp end": "EXP end",
    "exp end(jd)": "EXP end(JD)",
    "exp end(mjd)": "EXP end(MJD)",
    "is variable": "Is Variable",
}


def _column_key(name: Any) -> str:
    return clean_text(name).replace("\ufeff", "").casefold()


def _canonical_columns(columns: list[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    duplicates: list[str] = []
    for column in columns:
        canonical = COLUMN_ALIASES.get(_column_key(column))
        if not canonical:
            continue
        if canonical in mapping:
            duplicates.append(canonical)
        mapping[canonical] = column
    if duplicates:
        raise IngestionError(
            "Multiple columns map to the same Seestar field: " + ", ".join(sorted(set(duplicates)))
        )
    return mapping


@dataclass
class ParsedDataset:
    rows: list[dict[str, Any]]
    original_columns: list[str]
    target_names: list[str]
    jd_min: float | None
    jd_max: float | None
    warnings: list[str] = field(default_factory=list)

    @property
    def row_count(self) -> int:
        return len(self.rows)


@dataclass
class IngestResult:
    dataset_id: str
    row_count: int
    duplicate: bool
    target_names: list[str]
    warnings: list[str]
    original_filename: str


def _read_dataframe(data: bytes) -> pd.DataFrame:
    try:
        df = pd.read_csv(
            io.BytesIO(data),
            dtype=str,
            keep_default_na=False,
            encoding="utf-8-sig",
            skip_blank_lines=False,
        )
    except UnicodeDecodeError:
        try:
            df = pd.read_csv(
                io.BytesIO(data),
                dtype=str,
                keep_default_na=False,
                encoding="latin-1",
                skip_blank_lines=False,
            )
        except Exception as exc:  # pragma: no cover - defensive
            raise IngestionError(f"Could not read CSV: {exc}") from exc
    except Exception as exc:
        raise IngestionError(f"Could not read CSV: {exc}") from exc

    df.columns = [clean_text(column).replace("\ufeff", "") for column in df.columns]
    if any(not column for column in df.columns):
        raise IngestionError("The CSV contains one or more blank column names.")
    return df


def parse_seestar_csv(data: bytes, filename: str = "upload.csv") -> ParsedDataset:
    df = _read_dataframe(data)
    if df.empty:
        raise IngestionError("The CSV has no data rows.")

    mapping = _canonical_columns(list(df.columns))
    missing = [column for column in REQUIRED_CANONICAL if column not in mapping]
    if missing:
        raise IngestionError(
            "Missing required Seestar column(s): "
            + ", ".join(missing)
            + ". Expected Name, Mag(obs), Mag(err), EXP start(JD), and SNR."
        )

    warnings: list[str] = []
    rows: list[dict[str, Any]] = []
    skipped_blank = 0
    skipped_repeated_header = 0

    for index, row in df.iterrows():
        raw = {column: stringify(row[column]) for column in df.columns}
        if not any(value != "" for value in raw.values()):
            skipped_blank += 1
            continue

        name_value = clean_text(row[mapping["Name"]])
        mag_value = clean_text(row[mapping["Mag(obs)"]])
        if name_value.casefold() == "name" and mag_value.casefold() in {"mag(obs)", "magnitude"}:
            skipped_repeated_header += 1
            continue

        flags: list[str] = []
        target_name = name_value or "Unknown target"
        if not name_value:
            flags.append("missing target name")
        target_key = normalize_target_key(target_name)

        mag_obs = parse_float(row[mapping["Mag(obs)"]])
        mag_err = parse_float(row[mapping["Mag(err)"]])
        snr = parse_float(row[mapping["SNR"]])
        jd_start = parse_float(row[mapping["EXP start(JD)"]])

        if mag_obs is None:
            flags.append("missing or invalid Mag(obs)")
        if mag_err is None:
            flags.append("missing or invalid Mag(err)")
        elif mag_err <= 0:
            flags.append("non-positive Mag(err)")
        if snr is None:
            flags.append("missing or invalid SNR")
        if jd_start is None:
            mjd_column = mapping.get("EXP start(MJD)")
            mjd_value = parse_float(row[mjd_column]) if mjd_column else None
            if mjd_value is not None:
                jd_start = mjd_value + 2400000.5
                flags.append("JD derived from MJD")
            else:
                flags.append("missing or invalid EXP start(JD)")

        jd_end = None
        if end_column := mapping.get("EXP end(JD)"):
            jd_end = parse_float(row[end_column])
        if jd_end is None and (end_mjd_column := mapping.get("EXP end(MJD)")):
            end_mjd = parse_float(row[end_mjd_column])
            if end_mjd is not None:
                jd_end = end_mjd + 2400000.5

        parse_flags = "; ".join(flags)
        rows.append(
            {
                "source_row": int(index) + 2,
                "target_name": target_name,
                "target_key": target_key,
                "obs_type": clean_text(row[mapping["Type"]]) if "Type" in mapping else "",
                "ra": parse_float(row[mapping["RA"]]) if "RA" in mapping else None,
                "dec": parse_float(row[mapping["DEC"]]) if "DEC" in mapping else None,
                "mag_obs": mag_obs,
                "mag_err": mag_err,
                "jd_start": jd_start,
                "jd_end": jd_end,
                "local_start": clean_text(row[mapping["EXP start"]]) if "EXP start" in mapping else "",
                "local_end": clean_text(row[mapping["EXP end"]]) if "EXP end" in mapping else "",
                "exp_seconds": parse_seconds(row[mapping["EXP"]]) if "EXP" in mapping else None,
                "snr": snr,
                "valid_ref_stars": (
                    parse_int(row[mapping["Valid Reference Stars"]])
                    if "Valid Reference Stars" in mapping
                    else None
                ),
                "is_variable": (
                    (1 if parse_bool(row[mapping["Is Variable"]]) else 0)
                    if "Is Variable" in mapping and parse_bool(row[mapping["Is Variable"]]) is not None
                    else None
                ),
                "raw_json": json.dumps(raw, ensure_ascii=False),
                "parse_flags": parse_flags,
            }
        )

    if not rows:
        raise IngestionError("No observation rows were found in the CSV.")
    if skipped_repeated_header:
        warnings.append(f"Skipped {skipped_repeated_header} repeated header row(s).")
    if skipped_blank:
        warnings.append(f"Skipped {skipped_blank} blank row(s).")

    jds = [row["jd_start"] for row in rows if row["jd_start"] is not None]
    target_names = sorted({row["target_name"] for row in rows}, key=str.casefold)
    invalid_rows = sum(1 for row in rows if row["parse_flags"])
    if invalid_rows:
        warnings.append(
            f"{invalid_rows} row(s) had missing or invalid values. They were retained and flagged."
        )

    return ParsedDataset(
        rows=rows,
        original_columns=list(df.columns),
        target_names=target_names,
        jd_min=min(jds) if jds else None,
        jd_max=max(jds) if jds else None,
        warnings=warnings,
    )


def _alias_map() -> dict[str, str]:
    with database.connect() as conn:
        return {
            row["alias_key"]: row["target_key"]
            for row in conn.execute("SELECT alias_key, target_key FROM target_aliases")
        }


def _existing_dataset_for_hash(sha256: str) -> dict[str, Any] | None:
    with database.connect() as conn:
        row = conn.execute(
            "SELECT * FROM datasets WHERE sha256 = ? ORDER BY imported_at DESC LIMIT 1",
            (sha256,),
        ).fetchone()
    return dict(row) if row else None


def ingest_bytes(
    data: bytes,
    filename: str,
    *,
    notes: str = "",
    force: bool = False,
    show_warning: bool = False,
) -> IngestResult:
    clean_name = safe_filename(filename)
    sha256 = hashlib.sha256(data).hexdigest()
    existing = _existing_dataset_for_hash(sha256)
    if existing and not force:
        return IngestResult(
            dataset_id=existing["id"],
            row_count=int(existing["row_count"]),
            duplicate=True,
            target_names=json.loads(existing["target_names"] or "[]"),
            warnings=["This exact file has already been imported."],
            original_filename=filename,
        )

    parsed = parse_seestar_csv(data, filename)
    aliases = _alias_map()
    for row in parsed.rows:
        row["target_key"] = aliases.get(row["target_key"], row["target_key"])
    config.ensure_dirs()
    dataset_id = uuid.uuid4().hex
    stored_filename = f"{dataset_id}_{clean_name}"
    target_path = config.UPLOADS_DIR / stored_filename
    target_path.write_bytes(data)

    try:
        imported_at = database.utc_now()
        with database.connect() as conn:
            conn.execute(
                """
                INSERT INTO datasets(
                    id, original_filename, stored_filename, sha256, imported_at,
                    row_count, target_names, jd_min, jd_max, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    dataset_id,
                    filename,
                    stored_filename,
                    sha256,
                    imported_at,
                    parsed.row_count,
                    json.dumps(parsed.target_names, ensure_ascii=False),
                    parsed.jd_min,
                    parsed.jd_max,
                    notes,
                ),
            )
            for row in parsed.rows:
                conn.execute(
                    """
                    INSERT INTO observations(
                        dataset_id, source_row, target_name, target_key, obs_type, ra, dec,
                        mag_obs, mag_err, jd_start, jd_end, local_start, local_end,
                        exp_seconds, snr, valid_ref_stars, is_variable, raw_json, parse_flags
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        dataset_id,
                        row["source_row"],
                        row["target_name"],
                        row["target_key"],
                        row["obs_type"],
                        row["ra"],
                        row["dec"],
                        row["mag_obs"],
                        row["mag_err"],
                        row["jd_start"],
                        row["jd_end"],
                        row["local_start"],
                        row["local_end"],
                        row["exp_seconds"],
                        row["snr"],
                        row["valid_ref_stars"],
                        row["is_variable"],
                        row["raw_json"],
                        row["parse_flags"],
                    ),
                )
    except Exception:
        target_path.unlink(missing_ok=True)
        raise

    return IngestResult(
        dataset_id=dataset_id,
        row_count=parsed.row_count,
        duplicate=False,
        target_names=parsed.target_names,
        warnings=parsed.warnings,
        original_filename=filename,
    )


def ingest_path(path: Path, *, notes: str = "") -> IngestResult:
    return ingest_bytes(path.read_bytes(), path.name, notes=notes)


def original_file_path(dataset: dict[str, Any]) -> Path:
    return config.UPLOADS_DIR / dataset["stored_filename"]
