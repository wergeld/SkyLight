from __future__ import annotations

from datetime import datetime
from pathlib import Path

from streamlit.testing.v1 import AppTest

from starlight import conditions, database, exports

ROOT = Path(__file__).resolve().parent.parent


def test_all_pages_render(temp_data, sample_dataset, monkeypatch):
    monkeypatch.setattr(exports, "figure_png_bytes", lambda figure: None)

    for page in ("app.py", "pages/1_Logbook.py", "pages/2_Target_Catalog.py", "pages/3_Help.py"):
        app = AppTest.from_file(str(ROOT / page), default_timeout=60)
        app.run()
        assert not app.exception, f"{page}: {[str(item.value) for item in app.exception]}"


def test_link_select_all_toggles_every_observation(temp_data, sample_dataset, monkeypatch):
    monkeypatch.setattr(exports, "figure_png_bytes", lambda figure: None)

    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
    app.run()
    assert not app.exception
    target_key = app.selectbox(key="active_target").value["target_key"]
    scope = f"{target_key}_all_1"
    revision_key = f"link_select_revision_{scope}_False_0"
    select_all_key = f"link_select_all_button_{revision_key}"
    clear_key = f"link_clear_button_{revision_key}"

    app.button(key=select_all_key).click().run()
    assert not app.exception
    assert "163 observation(s) checked." in [item.value for item in app.caption]

    app.button(key=clear_key).click().run()
    assert not app.exception
    assert not any("observation(s) checked" in item.value for item in app.caption)


def test_logbook_conditions_lookup_fills_moon_field(temp_data, monkeypatch):
    monkeypatch.setattr(exports, "figure_png_bytes", lambda figure: None)
    database.set_setting("observer_latitude", "27.950000")
    database.set_setting("observer_longitude", "-82.457200")
    database.set_setting("observer_site_name", "Tampa")

    result = conditions.ConditionsLookup(
        moon_text="Waxing gibbous, 89% illuminated, 58? above horizon",
        weather_text="cloud 12% ? 21.5?C (historical reanalysis; Open-Meteo)",
        local_time=datetime(2026, 10, 22, 22, 0),
        timezone="America/New_York",
        source="historical reanalysis",
    )
    monkeypatch.setattr(conditions, "lookup_conditions", lambda *args, **kwargs: result)

    app = AppTest.from_file(str(ROOT / "pages/1_Logbook.py"), default_timeout=60)
    app.run()
    assert not app.exception
    app.text_input(key="new_logbook_date").set_value("2026-10-22")
    app.text_input(key="new_logbook_start").set_value("21:00:00")
    app.text_input(key="new_logbook_end").set_value("23:00:00")
    app.button(key="new_logbook_lookup_conditions").click().run()

    assert not app.exception
    assert "Moon: Waxing gibbous" in app.text_area(key="new_logbook_moon").value
    assert "cloud 12%" in app.text_area(key="new_logbook_moon").value


def test_new_linked_entry_conditions_lookup_fills_moon_field(temp_data, sample_dataset, monkeypatch):
    monkeypatch.setattr(exports, "figure_png_bytes", lambda figure: None)
    database.set_setting("observer_latitude", "27.950000")
    database.set_setting("observer_longitude", "-82.457200")
    database.set_setting("observer_site_name", "Tampa")

    result = conditions.ConditionsLookup(
        moon_text="Waxing gibbous, 89% illuminated, 58? above horizon",
        weather_text="cloud 12% ? 21.5?C (historical reanalysis; Open-Meteo)",
        local_time=datetime(2026, 10, 22, 22, 0),
        timezone="America/New_York",
        source="historical reanalysis",
    )
    monkeypatch.setattr(conditions, "lookup_conditions", lambda *args, **kwargs: result)

    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
    app.run()
    assert not app.exception
    target_key = app.selectbox(key="active_target").value["target_key"]
    scope = f"{target_key}_all_1"
    revision_key = f"link_select_revision_{scope}_False_0"
    app.button(key=f"link_select_all_button_{revision_key}").click().run()
    assert not app.exception
    prepare = next(
        item
        for item in app.button
        if item.label == "Prepare new logbook entry from checked"
    )
    prepare.click().run()
    assert not app.exception

    token = (
        str(app.session_state["pending_link_token"])
        .replace(" ", "_")
        .replace(":", "")
    )
    app.button(key=f"new_link_lookup_conditions_{token}").click().run()
    assert not app.exception
    moon_key = f"new_link_moon_{token}"
    assert "Moon: Waxing gibbous" in app.text_area(key=moon_key).value
    assert "cloud 12%" in app.text_area(key=moon_key).value


def test_observer_site_settings_save(temp_data):
    app = AppTest.from_file(str(ROOT / "pages/1_Logbook.py"), default_timeout=60)
    app.run()
    assert not app.exception
    app.text_input(key="observer_site_name_input").set_value("Tampa")
    app.text_input(key="observer_latitude_input").set_value("27.9506")
    app.text_input(key="observer_longitude_input").set_value("-82.4572")
    app.button(key="save_observer_site_button").click().run()

    assert not app.exception
    assert database.get_setting("observer_site_name") == "Tampa"
    assert database.get_setting("observer_latitude") == "27.950600"
    assert database.get_setting("observer_longitude") == "-82.457200"
