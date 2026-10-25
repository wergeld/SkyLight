from __future__ import annotations

import streamlit as st

from starlight import config, database, ui

ui.page_setup("Help", "❓")
ui.sidebar_common()

st.title("Help and workflow")
st.caption(f"{config.APP_NAME} {config.APP_VERSION} · local single-user observing workspace")

quick_tab, data_tab, science_tab, ops_tab = st.tabs(
    ["Quick Start", "Data & Backups", "Analysis Notes", "Docker & Troubleshooting"]
)

with quick_tab:
    st.subheader("Recommended workflow")
    st.markdown(
        """
1. **Upload Seestar CSV files** in the sidebar of the Observations page. Identical files are skipped by hash unless you explicitly re-import them.
2. **Inspect each target independently** with the target selector. StarLight does not merge targets or apply night-to-night offsets.
3. **Phase fold** with a known period and optional epoch. Save the period/epoch to seed the catalog for next time.
4. **Review quality flags** as prompts, not automatic rejections. No rows are removed.
5. **Select individual observations** in the Logbook Links tab and either create a new entry or attach them to an existing entry.
6. **Complete the logbook entry** with conditions, exposure, filter, and notes.
7. **Save your observing site** in the sidebar, then use **Look up Moon & weather** to fill editable conditions text.
8. **Export raw/analysis CSVs, plots, and the ZIP bundle** for the record.
        """
    )
    def page_link_or_markdown(path: str, label: str, icon: str, fallback: str) -> None:
        try:
            st.page_link(path, label=label, icon=icon, width="stretch")
        except Exception:
            st.markdown(f"[{icon} {label}]({fallback})")

    link_columns = st.columns(3)
    with link_columns[0]:
        page_link_or_markdown("app.py", "Observations", "🔭", "/")
    with link_columns[1]:
        page_link_or_markdown("pages/1_Logbook.py", "Logbook", "📓", "/Logbook")
    with link_columns[2]:
        page_link_or_markdown(
            "pages/2_Target_Catalog.py", "Target Catalog", "🗂️", "/Target_Catalog"
        )

    st.divider()
    st.subheader("Current database")
    counts = database.stats()
    metric_columns = st.columns(5)
    metric_columns[0].metric("Datasets", f"{counts['datasets']:,}")
    metric_columns[1].metric("Observations", f"{counts['observations']:,}")
    metric_columns[2].metric("Targets", f"{counts['targets']:,}")
    metric_columns[3].metric("Logbook entries", f"{counts['logbook_entries']:,}")
    metric_columns[4].metric("Linked observations", f"{counts['linked_observations']:,}")

    st.subheader("What StarLight deliberately does not do")
    st.markdown(
        """
- It does **not** merge separate targets into one light curve.
- It does **not** align nights by median, apply vertical offsets, smooth, or detrend.
- It does **not** correct timestamps between JD, BJD, UTC, and local time. The source time basis is preserved and displayed.
- It does **not** automatically delete duplicates, outliers, or low-SNR points.
- It does **not** search for periods automatically in this version.
        """
    )

with data_tab:
    st.subheader("Preservation model")
    st.markdown(
        """
- The original uploaded CSV bytes are archived under the data directory.
- Every original cell is stored as received in the observation's `raw_json` field.
- Parsed numeric values, derived night labels, elapsed time, phase, and quality flags are separate columns.
- Raw exports reconstruct the original column order and cell text, with provenance columns and `STARLIGHT_`-prefixed derived fields.
- Logbook links reference individual observations and never modify measurements.
        """
    )
    st.subheader("Where the data lives")
    st.code(
        f"Database: {config.DB_PATH}\nArchived CSVs: {config.UPLOADS_DIR}\nWorkbook seed: {config.WORKBOOK_PATH}"
    )
    st.info(
        "The Docker setup maps the container's data directory to a host volume. "
        "Back up that entire directory to preserve the database, raw files, logbook, and links."
    )
    st.subheader("Excel workbook interoperability")
    st.markdown(
        """
- The bundled Tampa workbook is seeded once on first launch.
- Manual workbook imports are available on **Logbook → Import / Export**.
- Logbook entries are matched by session ID, then by target/date/start/end to avoid duplicates.
- Workbook export includes Read Me, Target Catalog, Annual Plan, Observation Log, and References sheets.
        """
    )
    from starlight import workbook

    st.download_button(
        "Download the current workbook",
        data=workbook.export_workbook_bytes(),
        file_name="StarLight_Observing_Logbook.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    st.subheader("Moon and weather lookup")
    st.markdown(
        """
- Save latitude, longitude, and an optional site name in the sidebar.
- **Look up Moon & weather** uses the entry's local date and start/end times to fill editable text.
- Moon phase, illumination, and altitude are calculated locally with `ephem`.
- Weather is modeled/reanalysis data from the free [Open-Meteo](https://open-meteo.com/) API and requires internet access.
- The coordinates are sent to Open-Meteo for the weather request and remain stored locally in SQLite.
- Cloud, temperature, humidity, wind, and precipitation are context only; seeing and transparency remain manual.
        """
    )

with science_tab:
    st.subheader("Time coordinates")
    st.markdown(
        """
- **Calendar date** prefers the Seestar local `EXP start` text and falls back to UTC from `EXP start(JD)` when parsing fails.
- **Julian Date** is the raw JD from the CSV.
- **Elapsed (all nights)** uses one reference time for the selected target and preserves gaps.
- **Elapsed within each night** restarts at zero per file/night for display only.
- **Phase** is `((JD − epoch) / period) mod 1` using absolute JD. Observations are never shifted by night.
        """
    )
    st.subheader("Quality flags")
    st.markdown(
        """
Flags are advisory and can be tuned in the Observations sidebar:

- Missing or non-positive magnitude error
- Magnitude error above the threshold
- Missing or low SNR
- Missing JD
- Duplicate timestamps within a target/night (flagged, not removed)
- Possible local spike relative to nearby points

A real variable-star event can trigger the spike flag. Review the curve before excluding anything.
        """
    )
    st.subheader("Photometry summary")
    st.markdown(
        """
- Statistics describe the magnitudes currently selected for the target.
- Weighted means use `1 / Mag(err)^2`.
- Per-night summaries group by archived dataset plus local date, not by an assumed observing night.
- No night alignment or detrending is implied by the summary.
        """
    )

with ops_tab:
    st.subheader("Docker launch")
    st.code(
        "docker compose up --build\n\n"
        "# then open http://localhost:8501\n\n"
        "# stop without deleting data\n"
        "docker compose down"
    )
    st.caption(
        "The compose file mounts a named volume at /app/data. Removing the volume deletes the "
        "database and archived CSVs."
    )
    st.subheader("Local Python launch")
    st.code(
        "python -m venv .venv\n"
        ".venv\\Scripts\\Activate.ps1\n"
        "pip install -r requirements.txt\n"
        "streamlit run app.py"
    )
    st.subheader("Common issues")
    st.markdown(
        """
- **CSV rejected:** confirm it is a Seestar magnitude export with a magnitude column and `EXP start(JD)`.
- **Wrong period:** verify the units. The phase form uses days; minutes are shown for convenience.
- **Plot PNG button missing:** install `kaleido` or use the Plotly toolbar camera icon.
- **Workbook seed failed:** open Logbook → Import / Export and retry, or upload the workbook manually.
- **Weather lookup failed:** confirm internet access and that the observing site is saved; modeled data may be unavailable for dates outside the API range.
- **Port already in use:** change the host port in `docker-compose.yml`, for example `8502:8501`.
- **Permission errors:** ensure the Docker volume/data directory is writable by the container user.
        """
    )
    st.warning(
        "This version has no authentication and is intended for a trusted local machine or "
        "private network. Do not expose it directly to the public internet."
    )
