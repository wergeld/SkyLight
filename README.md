# StarLight

StarLight is a local, single-user Streamlit application for analyzing Seestar CSV
light curves and keeping a persistent variable-star observing logbook. It is built
around a strict preservation policy: uploaded CSVs are archived unchanged, every
original cell is stored, and no automatic night alignment or detrending is applied.

## Features

- Upload one or more Seestar magnitude CSVs and keep them in a local SQLite archive.
- Analyze each target independently; targets are never merged automatically.
- Plot raw light curves by local calendar time, raw Julian Date, global elapsed time,
  or per-night elapsed time for display.
- Phase fold on absolute JD with a known period and optional epoch.
- Review missing values, low SNR, large magnitude errors, duplicate timestamps, and
  possible local spikes without deleting any rows.
- Summarize photometry overall or per archived night/file.
- Link individual observations to a persistent logbook entry, reassign links, or
  unlink them without changing the measurements.
- Look up Moon phase, illumination, altitude, and modeled hourly weather for a saved
  observing site.
- Import and export a Tampa-style Excel observing workbook.
- Maintain a target catalog, aliases, annual plan, and AAVSO/SIMBAD/VizieR/VSP links.
- Export raw CSVs, analysis CSVs, Plotly HTML, optional PNG plots, and a ZIP bundle
  with metadata describing the exact settings used.

## Quick Start with Docker

Requirements: Docker Desktop or Docker Engine with Compose.

```bash
docker compose up --build
```

Open <http://localhost:8501>. Stop with `Ctrl+C`, or run detached and stop later:

```bash
docker compose up --build -d
docker compose down
```

The named volume `starlight_data` stores the database, archived CSV files, logbook,
and links. `docker compose down` keeps the volume. Do **not** use `docker compose down -v`
unless you intend to delete all StarLight data.

Convenience launchers:

- Windows: `launch.bat` or `.\launch.ps1`
- Linux/macOS: `./launch.sh`

## Local Python Setup

Python 3.11 or newer is recommended.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run app.py
```

On Linux/macOS, activate with `source .venv/bin/activate`. The app uses `data/` in the
project directory by default. Set `STARLIGHT_DATA_DIR` to store data elsewhere.

## Workflow

1. Upload one or more Seestar CSVs from the Observations sidebar.
2. Choose a target and inspect the light curve.
3. Enter a known period/epoch and save it to the target catalog if desired.
4. Review quality flags with the current thresholds. Flags are advisory only.
5. Open **Logbook Links**, use **Select all shown** or check individual observations, then create or select a logbook entry.
6. Complete the entry with conditions, exposure, filter, and notes. Session IDs are generated automatically.
7. Save your observing site in the sidebar, then use **Look up Moon & weather** to fill editable conditions text.
8. Export the raw CSV, analysis CSV, plots, or the complete ZIP bundle.

## Raw Data Preservation

- The uploaded file bytes are archived under the data directory.
- The original CSV cell strings are stored in `raw_json`.
- Parsed values live in separate database columns.
- Derived time and phase columns are display/analysis aids.
- Night labels are based on the archived dataset plus local date; they are not an
  inferred astronomical night boundary.
- Duplicate timestamps and outliers are flagged, never removed automatically.
- Logbook links point at individual observations and do not modify them.

StarLight does not apply night-to-night offsets, median normalization, timezone
correction, smoothing, automatic detrending, or automatic period searching.

## Moon and Weather Lookup

Save the observing site latitude, longitude, and optional name in the sidebar. The
Logbook and observation-linking forms can then fill their editable Moon/conditions text
from the entry date and local start/end times.

- Moon phase, illumination, and altitude are calculated locally with `ephem`.
- Weather comes from the free [Open-Meteo](https://open-meteo.com/) API. It is
  modeled/reanalysis data, not an on-site measurement, and it requires an internet
  connection.
- The observing coordinates are sent to Open-Meteo for the weather request; they remain
  stored locally in SQLite.
- Cloud cover, temperature, humidity, wind, and precipitation are context only. Seeing
  and transparency still require observer judgment.

## Pages

- **Observations** (`app.py`): upload, light curves, phase folding, quality review,
  photometry summaries, exports, and observation-to-logbook linking.
- **Logbook** (`pages/1_Logbook.py`): browse/edit entries, create entries, link or
  unlink observations, and import/export the workbook.
- **Target Catalog** (`pages/2_Target_Catalog.py`): catalog metadata, periods,
  aliases, annual plan, and online resources.
- **Help** (`pages/3_Help.py`): workflow, data policy, interpretation, and
  troubleshooting.

## Data Locations

Default local paths:

```text
data/starlight.db          SQLite database
data/uploads/              archived original CSV files
Tampa_Variable_Star_Observing_Logbook.xlsx   one-time seed workbook
```

In Docker, `/app/data` is the data directory and is mounted to the named volume.
Back up the entire data directory to preserve all state.

## Supported CSV Fields

Required after column normalization:

- `Name`
- `Mag(obs)`
- `Mag(err)`
- `EXP start(JD)`
- `SNR`

Recognized optional fields include `Type`, `RA`, `DEC`, `Valid Reference Stars`,
`EXP`, `EXP start`, `EXP start(MJD)`, `EXP end`, `EXP end(JD)`, `EXP end(MJD)`, and
`Is Variable`. Unknown columns are still preserved in the raw archive.

## Tests and Linting

```powershell
pip install -r requirements-dev.txt
python -m pytest
ruff check .
```

Tests cover sample CSV ingestion, raw-cell preservation, time and phase derivation,
quality flags, SQLite/logbook link behavior, Moon/weather parsing with mocked responses,
workbook import/export, plot/export generation, and a Streamlit smoke test of every page.

## Configuration

Environment variables:

- `STARLIGHT_DATA_DIR`: directory for the SQLite database and archived uploads.
- `STARLIGHT_WORKBOOK_PATH`: optional alternate seed workbook path.

Quality thresholds and the catalog period/epoch are editable in the UI and persisted
in SQLite.

## Limitations

- Single-user local design with no authentication. Do not expose it directly to the
  public internet.
- Moon and weather lookup requires internet access; weather is modeled, not measured.
- Automatic period searching is intentionally not implemented.
- The phase epoch is optional; a zero epoch uses JD 0 as the reference.
- PNG export requires a working `kaleido` installation. The Plotly toolbar can always
  export an image in the browser.
- Workbook logbook matching uses session ID, then target/date/start/end. Review the
  import summary after loading a heavily customized workbook.

## Troubleshooting

- **Port 8501 in use:** change the host side of the compose port mapping, for example
  `"8502:8501"`, and open <http://localhost:8502>.
- **CSV rejected:** verify it is a Seestar magnitude export and includes the required
  columns above.
- **Wrong phase:** the period field is in days; the UI also shows the equivalent minutes.
- **Workbook seed failed:** retry from **Logbook → Import / Export**, or upload the
  workbook manually there.
- **Permission error in Docker:** confirm the data volume is writable by the container
  user. A fresh named volume normally inherits the correct ownership from the image.
