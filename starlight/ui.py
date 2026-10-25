from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from . import bootstrap, conditions, config, database, resources
from .text import short_filename


def page_setup(title: str, icon: str = "✦") -> None:
    st.set_page_config(
        page_title=f"{title} · {config.APP_NAME}",
        page_icon=icon,
        layout="wide",
        initial_sidebar_state="expanded",
    )
    bootstrap.initialize()


def sidebar_common() -> None:
    st.sidebar.title(f"{config.APP_NAME}")
    st.sidebar.caption(config.APP_SUBTITLE)
    counts = database.stats()
    st.sidebar.markdown(
        f"**{counts['observations']:,}** observations · "
        f"**{counts['targets']:,}** targets  \n"
        f"**{counts['logbook_entries']:,}** logbook entries · "
        f"**{counts['linked_observations']:,}** linked"
    )
    st.sidebar.divider()
    with st.sidebar.expander("Data preservation policy", expanded=False):
        st.write(
            "StarLight archives the original CSV and every original cell value. "
            "It never applies night-to-night offsets, median normalization, timezone "
            "correction, or automatic outlier removal. Derived phase/elapsed columns "
            "are for display and analysis only."
        )
    st.sidebar.caption(f"Data directory: `{config.DATA_DIR}`")
    st.sidebar.caption("Local single-user mode — no authentication.")
    render_observer_site_settings()


def observer_coordinates() -> tuple[float, float, str] | None:
    latitude_text = database.get_setting("observer_latitude")
    longitude_text = database.get_setting("observer_longitude")
    if not latitude_text or not longitude_text:
        return None
    try:
        latitude = float(latitude_text)
        longitude = float(longitude_text)
    except ValueError:
        return None
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        return None
    site_name = database.get_setting("observer_site_name") or "saved observing site"
    return latitude, longitude, site_name


def render_observer_site_settings() -> None:
    with st.sidebar.expander("Observing site (Moon & weather)", expanded=False):
        st.caption(
            "Used by the logbook's Moon and weather lookup. Coordinates are stored "
            "locally in the database."
        )
        site_name = st.text_input(
            "Site name",
            value=database.get_setting("observer_site_name") or "",
            placeholder="Tampa, Florida",
            key="observer_site_name_input",
        )
        latitude_text = st.text_input(
            "Latitude",
            value=database.get_setting("observer_latitude") or "",
            placeholder="27.9506",
            key="observer_latitude_input",
        )
        longitude_text = st.text_input(
            "Longitude",
            value=database.get_setting("observer_longitude") or "",
            placeholder="-82.4572",
            key="observer_longitude_input",
        )
        if st.button(
            "Save observing site",
            width="stretch",
            key="save_observer_site_button",
        ):
            try:
                latitude = float(latitude_text)
                longitude = float(longitude_text)
            except ValueError:
                st.error("Enter numeric latitude and longitude values.")
            else:
                if not -90 <= latitude <= 90:
                    st.error("Latitude must be between -90 and 90.")
                elif not -180 <= longitude <= 180:
                    st.error("Longitude must be between -180 and 180.")
                else:
                    database.set_setting("observer_site_name", site_name.strip())
                    database.set_setting("observer_latitude", f"{latitude:.6f}")
                    database.set_setting("observer_longitude", f"{longitude:.6f}")
                    st.success("Observing site saved.")
        st.caption("Weather: Open-Meteo modeled data. Moon: local calculation.")


def conditions_lookup_caption() -> None:
    if observer_coordinates() is None:
        st.caption(
            "Save your observing site in the sidebar before using the Moon & weather lookup."
        )
    else:
        st.caption(
            "Weather is modeled by Open-Meteo; Moon position is calculated locally. "
            "Verify actual sky conditions manually."
        )


def show_conditions_status(status_key: str) -> None:
    status = st.session_state.pop(status_key, None)
    if not status:
        return
    level, message = status
    if level == "success":
        st.success(message)
    else:
        st.error(message)


def fill_conditions_from_state(
    date_key: str,
    start_key: str,
    end_key: str,
    moon_key: str,
    status_key: str,
) -> None:
    observer = observer_coordinates()
    if observer is None:
        st.session_state[status_key] = (
            "error",
            "Save your observing site in the sidebar before using the lookup.",
        )
        return
    latitude, longitude, site_name = observer
    date_local = str(st.session_state.get(date_key, ""))
    start_local = str(st.session_state.get(start_key, ""))
    end_local = str(st.session_state.get(end_key, ""))
    try:
        result = conditions.lookup_conditions(
            latitude,
            longitude,
            date_local,
            start_local,
            end_local,
        )
    except conditions.ConditionsError as exc:
        st.session_state[status_key] = ("error", str(exc))
        return
    except Exception as exc:
        st.session_state[status_key] = ("error", f"Conditions lookup failed: {exc}")
        return
    st.session_state[moon_key] = conditions.conditions_text(result)
    st.session_state[status_key] = (
        "success",
        (
            f"Filled Moon and weather for {result.local_time:%Y-%m-%d %H:%M} "
            f"{result.timezone} from {site_name} ({result.source}; modeled data)."
        ),
    )


def preservation_notice() -> None:
    st.info(
        "Raw observations are preserved unchanged. Light curves and phase folds use derived "
        "display coordinates only; no night-to-night shifts or automatic detrending are applied.",
        icon="🛡️",
    )


def target_metadata(target_name: str, target_key: str) -> dict[str, Any]:
    return resources.target_metadata(target_name, target_key)


def render_target_summary(target_name: str, target_key: str, *, compact: bool = False) -> None:
    meta = target_metadata(target_name, target_key)
    if not meta or (not meta.get("variable_type") and not meta.get("brightness_range")):
        st.caption(
            "This target is not in the catalog yet. Add its metadata and aliases in Target Catalog."
        )
        return
    period = meta.get("period_days")
    period_text = ""
    if period:
        try:
            period_text = f"{float(period):.8f} d ({float(period) * 1440:.2f} min)"
        except (TypeError, ValueError):
            period_text = str(period)
    else:
        period_text = str(meta.get("period_timescale") or "not recorded")
    if compact:
        st.caption(
            " · ".join(
                item
                for item in [
                    str(meta.get("variable_type") or ""),
                    str(meta.get("constellation") or ""),
                    str(meta.get("brightness_range") or ""),
                    f"Period: {period_text}" if period_text else "",
                ]
                if item
            )
        )
        return
    columns = st.columns(4)
    columns[0].metric("Variable type", str(meta.get("variable_type") or "—"))
    columns[1].metric("Constellation", str(meta.get("constellation") or "—"))
    columns[2].metric("Brightness range", str(meta.get("brightness_range") or "—"))
    columns[3].metric("Period", period_text or "—")
    notes = str(meta.get("notes") or "").strip()
    if notes:
        st.caption(notes)


def render_online_resources(target_name: str, target_key: str) -> None:
    links = resources.get_target_resources(target_name, target_key)
    if not links:
        return
    with st.expander("Online resources for this target", expanded=False):
        for item in links:
            label = str(item.get("label") or item.get("url"))
            url = str(item.get("url") or "")
            category = str(item.get("category") or "")
            note = str(item.get("notes") or "")
            prefix = f"**{category}:** " if category else ""
            suffix = f" — {note}" if note else ""
            st.markdown(f"- {prefix}[{label}]({url}){suffix}")


def dataset_label(row: Any) -> str:
    filename = short_filename(str(row.get("original_filename", "")), 52)
    count = int(row.get("observation_count", row.get("row_count", 0)) or 0)
    imported = str(row.get("imported_at", ""))[:10]
    return f"{filename} · {count} rows · {imported}"


def format_number(value: Any, digits: int = 3) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def download_plot_buttons(
    figure,
    *,
    stem: str,
    key_prefix: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    from . import exports

    columns = st.columns([1, 1, 2])
    html_bytes = exports.figure_html_bytes(figure)
    columns[0].download_button(
        "Download plot HTML",
        data=html_bytes,
        file_name=f"{stem}.html",
        mime="text/html",
        key=f"{key_prefix}_html",
        width="stretch",
    )
    png_bytes = exports.figure_png_bytes(figure)
    if png_bytes:
        columns[1].download_button(
            "Download plot PNG",
            data=png_bytes,
            file_name=f"{stem}.png",
            mime="image/png",
            key=f"{key_prefix}_png",
            width="stretch",
        )
    else:
        columns[1].caption("PNG export needs kaleido; the chart toolbar still exports PNG.")
    columns[2].caption(
        "Plot files contain the current selected observations only. Raw data exports remain complete."
    )


def query_param(name: str) -> str | None:
    value = st.query_params.get(name)
    if isinstance(value, list):
        return value[0] if value else None
    return value


def set_view_observations(*, entry_id: int | None = None, target_key: str | None = None) -> None:
    if entry_id is not None:
        st.query_params["entry_id"] = str(entry_id)
    if target_key:
        st.query_params["target"] = target_key
    st.switch_page("app.py")


def clear_view_filters() -> None:
    for key in ("entry_id", "target", "linked_only"):
        if key in st.query_params:
            del st.query_params[key]
