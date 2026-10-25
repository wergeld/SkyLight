from __future__ import annotations

from starlight import database


def test_catalog_aliases_and_resources(temp_data):
    target_key = database.upsert_catalog_target(
        {
            "target_name": "DY Pegasi",
            "variable_type": "Delta Scuti",
            "period_days": 105.0 / 1440.0,
        }
    )
    database.add_alias("DY Peg", target_key)

    assert database.resolve_alias_key("DY Peg") == "dy pegasi"
    target = database.get_catalog_target("dy peg")
    assert target["target_name"] == "DY Pegasi"
    assert "dy peg" in target["aliases"]

    database.upsert_resource(
        {
            "target_key": None,
            "label": "AAVSO",
            "url": "https://www.aavso.org/",
            "category": "AAVSO",
        }
    )
    database.upsert_resource(
        {
            "target_key": None,
            "label": "AAVSO",
            "url": "https://www.aavso.org/",
            "category": "AAVSO updated",
        }
    )
    global_resources = [item for item in database.get_resources() if not item["target_key"]]
    assert len(global_resources) == 1
    assert global_resources[0]["category"] == "AAVSO updated"

    database.delete_catalog_target(target_key)
    assert database.get_catalog().empty
    assert database.resolve_alias_key("DY Peg") == "dy peg"


def test_logbook_one_active_link_per_observation(observations):
    ids = observations["id"].astype(int).tolist()[:3]
    first = database.create_logbook_entry(
        {
            "session_id": "S-001",
            "target_name": "DY Pegasi",
            "date_local": "2026-10-22",
            "start_local": "21:29:46",
            "end_local": "22:52:26",
        },
        observation_ids=ids,
    )
    second = database.create_logbook_entry(
        {
            "session_id": "S-002",
            "target_name": "DY Pegasi",
            "date_local": "2026-10-23",
        }
    )

    assert len(database.get_entry_observations(first)) == 3
    database.link_observations(ids[:2], second)
    assert len(database.get_entry_observations(first)) == 1
    assert len(database.get_entry_observations(second)) == 2

    links = database.get_linked_entries_for_observations(ids)
    assert len(links) == 3
    assert links["observation_id"].is_unique
    assert set(links["entry_id"]) == {first, second}

    database.unlink_observations(ids[:2])
    assert len(database.get_entry_observations(second)) == 0
    assert len(database.get_observations(target_key="dy pegasi", unlinked_only=True)) == 162

    database.delete_logbook_entry(first)
    assert len(database.get_observations(target_key="dy pegasi", unlinked_only=True)) == 163


def test_session_ids_are_made_unique(temp_data):
    first = database.create_logbook_entry({"session_id": "S-1", "target_name": "A"})
    second = database.create_logbook_entry({"session_id": "S-1", "target_name": "B"})
    assert database.get_logbook_entry(first)["session_id"] == "S-1"
    assert database.get_logbook_entry(second)["session_id"] == "S-1-2"


def test_blank_session_id_is_generated_and_unique(temp_data):
    first = database.create_logbook_entry(
        {"target_name": "DY Pegasi", "date_local": "2026-10-22"}
    )
    second = database.create_logbook_entry(
        {"target_name": "DY Pegasi", "date_local": "2026-10-22"}
    )
    assert database.get_logbook_entry(first)["session_id"] == "S-20261022-dy-pegasi"
    assert database.get_logbook_entry(second)["session_id"] == "S-20261022-dy-pegasi-2"


def test_deleting_dataset_retains_logbook_entry(observations, sample_dataset):
    entry_id = database.create_logbook_entry(
        {"session_id": "S-keep", "target_name": "DY Pegasi"},
        observation_ids=[int(observations["id"].iloc[0])],
    )
    database.delete_dataset(sample_dataset.dataset_id)

    assert database.get_observations().empty
    assert database.get_logbook_entry(entry_id) is not None
    assert database.get_entry_observations(entry_id).empty
