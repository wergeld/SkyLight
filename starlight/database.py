from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

import pandas as pd

from . import config
from .text import normalize_target_key, target_slug

SCHEMA_VERSION = 1

LOG_BOOK_COLUMNS = [
    "session_id",
    "target_name",
    "target_key",
    "date_local",
    "start_local",
    "end_local",
    "time_standard",
    "filter",
    "exposure_s",
    "frames",
    "settings",
    "transparency",
    "seeing",
    "moon",
    "csv_filename",
    "notes",
    "processed",
]


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    config.ensure_dirs()
    conn = sqlite3.connect(config.DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    config.ensure_dirs()
    with connect() as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS datasets (
                id TEXT PRIMARY KEY,
                original_filename TEXT NOT NULL,
                stored_filename TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                imported_at TEXT NOT NULL,
                row_count INTEGER NOT NULL,
                target_names TEXT NOT NULL,
                jd_min REAL,
                jd_max REAL,
                notes TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_datasets_sha256 ON datasets(sha256);

            CREATE TABLE IF NOT EXISTS observations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dataset_id TEXT NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
                source_row INTEGER NOT NULL,
                target_name TEXT NOT NULL,
                target_key TEXT NOT NULL,
                obs_type TEXT,
                ra REAL,
                dec REAL,
                mag_obs REAL,
                mag_err REAL,
                jd_start REAL,
                jd_end REAL,
                local_start TEXT,
                local_end TEXT,
                exp_seconds REAL,
                snr REAL,
                valid_ref_stars INTEGER,
                is_variable INTEGER,
                raw_json TEXT NOT NULL,
                parse_flags TEXT NOT NULL DEFAULT '',
                UNIQUE(dataset_id, source_row)
            );
            CREATE INDEX IF NOT EXISTS idx_obs_dataset ON observations(dataset_id);
            CREATE INDEX IF NOT EXISTS idx_obs_target_jd ON observations(target_key, jd_start);

            CREATE TABLE IF NOT EXISTS logbook_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL UNIQUE,
                target_name TEXT NOT NULL,
                target_key TEXT NOT NULL,
                date_local TEXT,
                start_local TEXT,
                end_local TEXT,
                time_standard TEXT,
                filter TEXT,
                exposure_s REAL,
                frames INTEGER,
                settings TEXT,
                transparency TEXT,
                seeing TEXT,
                moon TEXT,
                csv_filename TEXT,
                notes TEXT,
                processed INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_logbook_target ON logbook_entries(target_key, date_local);

            CREATE TABLE IF NOT EXISTS observation_logbook_links (
                observation_id INTEGER PRIMARY KEY REFERENCES observations(id) ON DELETE CASCADE,
                logbook_entry_id INTEGER NOT NULL REFERENCES logbook_entries(id) ON DELETE CASCADE,
                linked_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_links_entry ON observation_logbook_links(logbook_entry_id);

            CREATE TABLE IF NOT EXISTS target_catalog (
                target_key TEXT PRIMARY KEY,
                target_name TEXT NOT NULL,
                common_designation TEXT,
                variable_type TEXT,
                constellation TEXT,
                brightness_range TEXT,
                period_days REAL,
                epoch_jd REAL,
                period_timescale TEXT,
                season TEXT,
                session_length TEXT,
                cadence TEXT,
                project_goal TEXT,
                notes TEXT
            );

            CREATE TABLE IF NOT EXISTS target_aliases (
                alias_key TEXT PRIMARY KEY,
                target_key TEXT NOT NULL REFERENCES target_catalog(target_key) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS annual_plan (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                when_text TEXT,
                primary_targets TEXT,
                what_to_do TEXT,
                time_per_target TEXT,
                repeat_cadence TEXT,
                deliverable TEXT,
                priority TEXT
            );

            CREATE TABLE IF NOT EXISTS resources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                target_key TEXT,
                label TEXT NOT NULL,
                url TEXT NOT NULL,
                category TEXT,
                notes TEXT,
                source TEXT
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_resources_unique
                ON resources(IFNULL(target_key, ''), label, url);

            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )
        row = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
        if row is None:
            conn.execute("INSERT INTO schema_version(version) VALUES (?)", (SCHEMA_VERSION,))
        elif int(row["version"]) < SCHEMA_VERSION:
            conn.execute("UPDATE schema_version SET version = ?", (SCHEMA_VERSION,))


def get_setting(key: str, default: str | None = None) -> str | None:
    with connect() as conn:
        row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO app_settings(key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )


def resolve_alias_key(key: str) -> str:
    key = normalize_target_key(key)
    if not key:
        return key
    with connect() as conn:
        row = conn.execute(
            "SELECT target_key FROM target_aliases WHERE alias_key = ?", (key,)
        ).fetchone()
    return row["target_key"] if row else key


def _alias_keys_for(canonical_key: str) -> list[str]:
    with connect() as conn:
        aliases = [
            row["alias_key"]
            for row in conn.execute(
                "SELECT alias_key FROM target_aliases WHERE target_key = ?", (canonical_key,)
            )
        ]
        observed = [
            row["target_key"]
            for row in conn.execute("SELECT DISTINCT target_key FROM observations")
        ]
    keys = {canonical_key, *aliases}
    for key in observed:
        if resolve_alias_key(key) == canonical_key:
            keys.add(key)
    return sorted(keys)


def list_datasets() -> pd.DataFrame:
    with connect() as conn:
        return pd.read_sql_query(
            """
            SELECT d.*,
                   (SELECT COUNT(*) FROM observations o WHERE o.dataset_id = d.id) AS observation_count
            FROM datasets d
            ORDER BY d.imported_at DESC, d.original_filename
            """,
            conn,
        )


def get_dataset(dataset_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM datasets WHERE id = ?", (dataset_id,)).fetchone()
    return dict(row) if row else None


def delete_dataset(dataset_id: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM datasets WHERE id = ?", (dataset_id,))


def get_observations(
    *,
    dataset_ids: Sequence[str] | None = None,
    target_key: str | None = None,
    observation_ids: Sequence[int] | None = None,
    entry_id: int | None = None,
    unlinked_only: bool = False,
) -> pd.DataFrame:
    sql = [
        """
        SELECT o.*, d.original_filename AS source_file, d.imported_at, d.sha256,
               l.logbook_entry_id,
               e.session_id AS logbook_session_id,
               e.target_name AS logbook_target_name
        FROM observations o
        JOIN datasets d ON d.id = o.dataset_id
        LEFT JOIN observation_logbook_links l ON l.observation_id = o.id
        LEFT JOIN logbook_entries e ON e.id = l.logbook_entry_id
        WHERE 1 = 1
        """
    ]
    params: list[Any] = []
    if dataset_ids:
        placeholders = ",".join("?" for _ in dataset_ids)
        sql.append(f"AND o.dataset_id IN ({placeholders})")
        params.extend(dataset_ids)
    if target_key:
        keys = _alias_keys_for(normalize_target_key(target_key))
        placeholders = ",".join("?" for _ in keys)
        sql.append(f"AND o.target_key IN ({placeholders})")
        params.extend(keys)
    if observation_ids:
        placeholders = ",".join("?" for _ in observation_ids)
        sql.append(f"AND o.id IN ({placeholders})")
        params.extend([int(value) for value in observation_ids])
    if entry_id is not None:
        sql.append("AND l.logbook_entry_id = ?")
        params.append(int(entry_id))
    if unlinked_only:
        sql.append("AND l.observation_id IS NULL")
    sql.append("ORDER BY o.target_name, o.jd_start, o.source_row")
    with connect() as conn:
        return pd.read_sql_query(" ".join(sql), conn, params=params)


def list_observed_targets() -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT target_key, target_name, COUNT(*) AS count,
                   MIN(jd_start) AS jd_min, MAX(jd_start) AS jd_max
            FROM observations
            GROUP BY target_key, target_name
            """
        ).fetchall()
        catalog = {
            row["target_key"]: row["target_name"]
            for row in conn.execute("SELECT target_key, target_name FROM target_catalog")
        }
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        canonical = resolve_alias_key(row["target_key"])
        item = grouped.setdefault(
            canonical,
            {
                "target_key": canonical,
                "target_name": catalog.get(canonical, row["target_name"]),
                "count": 0,
                "jd_min": row["jd_min"],
                "jd_max": row["jd_max"],
            },
        )
        item["count"] += int(row["count"])
        item["jd_min"] = min(filter(None, [item["jd_min"], row["jd_min"]]), default=None)
        item["jd_max"] = max(filter(None, [item["jd_max"], row["jd_max"]]), default=None)
    return sorted(grouped.values(), key=lambda item: item["target_name"].casefold())


def get_catalog() -> pd.DataFrame:
    with connect() as conn:
        return pd.read_sql_query(
            "SELECT * FROM target_catalog ORDER BY target_name COLLATE NOCASE", conn
        )


def get_catalog_target(target_key: str) -> dict[str, Any] | None:
    canonical = resolve_alias_key(target_key)
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM target_catalog WHERE target_key = ?", (canonical,)
        ).fetchone()
        if row is None:
            return None
        data = dict(row)
        data["aliases"] = [
            alias["alias_key"]
            for alias in conn.execute(
                "SELECT alias_key FROM target_aliases WHERE target_key = ? ORDER BY alias_key",
                (canonical,),
            )
        ]
    return data


def upsert_catalog_target(data: dict[str, Any]) -> str:
    target_name = str(data.get("target_name") or data.get("target") or "").strip()
    if not target_name:
        raise ValueError("Target name is required.")
    target_key = normalize_target_key(data.get("target_key") or target_name)
    values = {
        "target_key": target_key,
        "target_name": target_name,
        "common_designation": data.get("common_designation", ""),
        "variable_type": data.get("variable_type", ""),
        "constellation": data.get("constellation", ""),
        "brightness_range": data.get("brightness_range", ""),
        "period_days": data.get("period_days"),
        "epoch_jd": data.get("epoch_jd"),
        "period_timescale": data.get("period_timescale", ""),
        "season": data.get("season", ""),
        "session_length": data.get("session_length", ""),
        "cadence": data.get("cadence", ""),
        "project_goal": data.get("project_goal", ""),
        "notes": data.get("notes", ""),
    }
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO target_catalog(
                target_key, target_name, common_designation, variable_type, constellation,
                brightness_range, period_days, epoch_jd, period_timescale, season,
                session_length, cadence, project_goal, notes
            ) VALUES (
                :target_key, :target_name, :common_designation, :variable_type, :constellation,
                :brightness_range, :period_days, :epoch_jd, :period_timescale, :season,
                :session_length, :cadence, :project_goal, :notes
            )
            ON CONFLICT(target_key) DO UPDATE SET
                target_name = excluded.target_name,
                common_designation = excluded.common_designation,
                variable_type = excluded.variable_type,
                constellation = excluded.constellation,
                brightness_range = excluded.brightness_range,
                period_days = COALESCE(excluded.period_days, target_catalog.period_days),
                epoch_jd = COALESCE(excluded.epoch_jd, target_catalog.epoch_jd),
                period_timescale = excluded.period_timescale,
                season = excluded.season,
                session_length = excluded.session_length,
                cadence = excluded.cadence,
                project_goal = excluded.project_goal,
                notes = excluded.notes
            """,
            values,
        )
    return target_key


def update_target_period(target_key: str, period_days: float | None, epoch_jd: float | None) -> None:
    canonical = resolve_alias_key(target_key)
    with connect() as conn:
        conn.execute(
            "UPDATE target_catalog SET period_days = ?, epoch_jd = ? WHERE target_key = ?",
            (period_days, epoch_jd, canonical),
        )


def delete_catalog_target(target_key: str) -> None:
    canonical = resolve_alias_key(target_key)
    with connect() as conn:
        conn.execute("DELETE FROM resources WHERE target_key = ?", (canonical,))
        conn.execute("DELETE FROM target_catalog WHERE target_key = ?", (canonical,))


def add_alias(alias: str, target_key: str) -> None:
    alias_key = normalize_target_key(alias)
    canonical = resolve_alias_key(target_key)
    if not alias_key or alias_key == canonical:
        return
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO target_aliases(alias_key, target_key) VALUES (?, ?)
            ON CONFLICT(alias_key) DO UPDATE SET target_key = excluded.target_key
            """,
            (alias_key, canonical),
        )


def delete_alias(alias: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM target_aliases WHERE alias_key = ?", (normalize_target_key(alias),))


def get_annual_plan() -> pd.DataFrame:
    with connect() as conn:
        return pd.read_sql_query("SELECT * FROM annual_plan ORDER BY id", conn)


def get_resources(target_key: str | None = None) -> list[dict[str, Any]]:
    with connect() as conn:
        if target_key:
            canonical = resolve_alias_key(target_key)
            rows = conn.execute(
                """
                SELECT * FROM resources
                WHERE target_key = ? OR target_key IS NULL
                ORDER BY CASE WHEN target_key IS NULL THEN 1 ELSE 0 END, category, label
                """,
                (canonical,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM resources ORDER BY target_key, category, label"
            ).fetchall()
    return [dict(row) for row in rows]


def upsert_resource(data: dict[str, Any]) -> None:
    target_key = data.get("target_key")
    if target_key:
        target_key = resolve_alias_key(target_key)
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO resources(target_key, label, url, category, notes, source)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(IFNULL(target_key, ''), label, url) DO UPDATE SET
                category = excluded.category,
                notes = excluded.notes,
                source = excluded.source
            """,
            (
                target_key or None,
                str(data.get("label") or "").strip(),
                str(data.get("url") or "").strip(),
                data.get("category", ""),
                data.get("notes", ""),
                data.get("source", ""),
            ),
        )


def delete_resource(resource_id: int) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM resources WHERE id = ?", (resource_id,))


def list_logbook_entries(
    *, search: str | None = None, target_key: str | None = None
) -> pd.DataFrame:
    sql = [
        """
        SELECT e.*,
               (SELECT COUNT(*) FROM observation_logbook_links l
                WHERE l.logbook_entry_id = e.id) AS linked_count
        FROM logbook_entries e
        WHERE 1 = 1
        """
    ]
    params: list[Any] = []
    if search:
        sql.append(
            "(e.session_id LIKE ? OR e.target_name LIKE ? OR e.notes LIKE ? OR e.csv_filename LIKE ?)"
        )
        needle = f"%{search}%"
        params.extend([needle, needle, needle, needle])
    if target_key:
        keys = _alias_keys_for(resolve_alias_key(target_key))
        placeholders = ",".join("?" for _ in keys)
        sql.append(f"AND e.target_key IN ({placeholders})")
        params.extend(keys)
    sql.append("ORDER BY e.date_local DESC, e.start_local DESC, e.session_id DESC")
    with connect() as conn:
        return pd.read_sql_query(" ".join(sql), conn, params=params)


def get_logbook_entry(entry_id: int) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM logbook_entries WHERE id = ?", (entry_id,)).fetchone()
    return dict(row) if row else None


def _unique_session_id(conn: sqlite3.Connection, candidate: str) -> str:
    base = candidate.strip() or "SESSION"
    current = base
    index = 2
    while conn.execute(
        "SELECT 1 FROM logbook_entries WHERE session_id = ?", (current,)
    ).fetchone():
        current = f"{base}-{index}"
        index += 1
    return current


def create_logbook_entry(
    data: dict[str, Any], *, observation_ids: Sequence[int] | None = None
) -> int:
    target_name = str(data.get("target_name") or data.get("target") or "").strip()
    if not target_name:
        raise ValueError("Target is required.")
    target_key = resolve_alias_key(data.get("target_key") or normalize_target_key(target_name))
    now = utc_now()
    date_local = str(data.get("date_local") or "").strip()
    session_id = str(data.get("session_id") or "").strip()
    if not session_id:
        stamp = date_local.replace("-", "") or datetime.now().strftime("%Y%m%d")
        session_id = f"S-{stamp}-{target_slug(target_name)}"
    values = {
        "session_id": session_id,
        "target_name": target_name,
        "target_key": target_key,
        "date_local": date_local,
        "start_local": data.get("start_local", ""),
        "end_local": data.get("end_local", ""),
        "time_standard": data.get("time_standard", config.TIME_STANDARD),
        "filter": data.get("filter", ""),
        "exposure_s": data.get("exposure_s"),
        "frames": data.get("frames"),
        "settings": data.get("settings", ""),
        "transparency": data.get("transparency", ""),
        "seeing": data.get("seeing", ""),
        "moon": data.get("moon", ""),
        "csv_filename": data.get("csv_filename", ""),
        "notes": data.get("notes", ""),
        "processed": 1 if data.get("processed") else 0,
        "created_at": now,
        "updated_at": now,
    }
    with connect() as conn:
        values["session_id"] = _unique_session_id(conn, session_id)
        cursor = conn.execute(
            """
            INSERT INTO logbook_entries(
                session_id, target_name, target_key, date_local, start_local, end_local,
                time_standard, filter, exposure_s, frames, settings, transparency,
                seeing, moon, csv_filename, notes, processed, created_at, updated_at
            ) VALUES (
                :session_id, :target_name, :target_key, :date_local, :start_local, :end_local,
                :time_standard, :filter, :exposure_s, :frames, :settings, :transparency,
                :seeing, :moon, :csv_filename, :notes, :processed, :created_at, :updated_at
            )
            """,
            values,
        )
        entry_id = int(cursor.lastrowid)
        if observation_ids:
            now_link = utc_now()
            for observation_id in observation_ids:
                conn.execute(
                    """
                    INSERT INTO observation_logbook_links(observation_id, logbook_entry_id, linked_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(observation_id) DO UPDATE SET
                        logbook_entry_id = excluded.logbook_entry_id,
                        linked_at = excluded.linked_at
                    """,
                    (int(observation_id), entry_id, now_link),
                )
    return entry_id


def update_logbook_entry(entry_id: int, data: dict[str, Any]) -> None:
    current = get_logbook_entry(entry_id)
    if not current:
        raise ValueError("Logbook entry not found.")
    target_name = str(data.get("target_name") or current["target_name"]).strip()
    target_key = resolve_alias_key(data.get("target_key") or normalize_target_key(target_name))
    values = {
        "id": entry_id,
        "session_id": str(data.get("session_id") or current["session_id"]).strip(),
        "target_name": target_name,
        "target_key": target_key,
        "date_local": data.get("date_local", current["date_local"]),
        "start_local": data.get("start_local", current["start_local"]),
        "end_local": data.get("end_local", current["end_local"]),
        "time_standard": data.get("time_standard", current["time_standard"]),
        "filter": data.get("filter", current["filter"]),
        "exposure_s": data.get("exposure_s", current["exposure_s"]),
        "frames": data.get("frames", current["frames"]),
        "settings": data.get("settings", current["settings"]),
        "transparency": data.get("transparency", current["transparency"]),
        "seeing": data.get("seeing", current["seeing"]),
        "moon": data.get("moon", current["moon"]),
        "csv_filename": data.get("csv_filename", current["csv_filename"]),
        "notes": data.get("notes", current["notes"]),
        "processed": 1 if data.get("processed", current["processed"]) else 0,
        "updated_at": utc_now(),
    }
    with connect() as conn:
        conn.execute(
            """
            UPDATE logbook_entries SET
                session_id = :session_id, target_name = :target_name, target_key = :target_key,
                date_local = :date_local, start_local = :start_local, end_local = :end_local,
                time_standard = :time_standard, filter = :filter, exposure_s = :exposure_s,
                frames = :frames, settings = :settings, transparency = :transparency,
                seeing = :seeing, moon = :moon, csv_filename = :csv_filename,
                notes = :notes, processed = :processed, updated_at = :updated_at
            WHERE id = :id
            """,
            values,
        )


def delete_logbook_entry(entry_id: int) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM logbook_entries WHERE id = ?", (entry_id,))


def link_observations(observation_ids: Iterable[int], entry_id: int) -> int:
    ids = [int(value) for value in observation_ids]
    if not ids:
        return 0
    now = utc_now()
    with connect() as conn:
        exists = conn.execute(
            "SELECT 1 FROM logbook_entries WHERE id = ?", (int(entry_id),)
        ).fetchone()
        if not exists:
            raise ValueError("Logbook entry not found.")
        for observation_id in ids:
            conn.execute(
                """
                INSERT INTO observation_logbook_links(observation_id, logbook_entry_id, linked_at)
                VALUES (?, ?, ?)
                ON CONFLICT(observation_id) DO UPDATE SET
                    logbook_entry_id = excluded.logbook_entry_id,
                    linked_at = excluded.linked_at
                """,
                (observation_id, int(entry_id), now),
            )
    return len(ids)


def unlink_observations(observation_ids: Iterable[int]) -> int:
    ids = [int(value) for value in observation_ids]
    if not ids:
        return 0
    placeholders = ",".join("?" for _ in ids)
    with connect() as conn:
        conn.execute(
            f"DELETE FROM observation_logbook_links WHERE observation_id IN ({placeholders})",
            ids,
        )
    return len(ids)


def get_entry_observations(entry_id: int) -> pd.DataFrame:
    return get_observations(entry_id=entry_id)


def get_linked_entries_for_observations(observation_ids: Sequence[int]) -> pd.DataFrame:
    if not observation_ids:
        return pd.DataFrame()
    placeholders = ",".join("?" for _ in observation_ids)
    with connect() as conn:
        return pd.read_sql_query(
            f"""
            SELECT l.observation_id, e.id AS entry_id, e.session_id, e.target_name
            FROM observation_logbook_links l
            JOIN logbook_entries e ON e.id = l.logbook_entry_id
            WHERE l.observation_id IN ({placeholders})
            """,
            conn,
            params=[int(value) for value in observation_ids],
        )


def apply_catalog_period_defaults() -> None:
    with connect() as conn:
        for key, period in config.CATALOG_PERIOD_DAYS.items():
            if period is None:
                continue
            conn.execute(
                "UPDATE target_catalog SET period_days = COALESCE(period_days, ?) WHERE target_key = ?",
                (period, key),
            )


def seed_aliases() -> None:
    with connect() as conn:
        catalog = conn.execute(
            "SELECT target_key, target_name, common_designation FROM target_catalog"
        ).fetchall()
        for row in catalog:
            aliases = list(config.CATALOG_ALIASES.get(row["target_key"], []))
            if row["common_designation"]:
                aliases.append(row["common_designation"])
            for alias in aliases:
                alias_key = normalize_target_key(alias)
                if not alias_key or alias_key == row["target_key"]:
                    continue
                conn.execute(
                    """
                    INSERT INTO target_aliases(alias_key, target_key) VALUES (?, ?)
                    ON CONFLICT(alias_key) DO UPDATE SET target_key = excluded.target_key
                    """,
                    (alias_key, row["target_key"]),
                )


def stats() -> dict[str, int]:
    with connect() as conn:
        def count(table: str) -> int:
            return int(conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"])

        return {
            "datasets": count("datasets"),
            "observations": count("observations"),
            "targets": int(
                conn.execute("SELECT COUNT(DISTINCT target_key) AS n FROM observations").fetchone()["n"]
            ),
            "logbook_entries": count("logbook_entries"),
            "linked_observations": count("observation_logbook_links"),
        }


def raw_rows_for_dataset(dataset_id: str) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT source_row, raw_json FROM observations WHERE dataset_id = ? ORDER BY source_row",
            (dataset_id,),
        ).fetchall()
    return [
        {"source_row": row["source_row"], "raw": json.loads(row["raw_json"])} for row in rows
    ]
