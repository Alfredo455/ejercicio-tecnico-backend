from decimal import Decimal

import pytest

from app.ingestion import load as load_module
from app.ingestion.load import format_summary, load_file

T1 = "2026-09-04T04:00:00Z"
T1_OFFSET = "2026-09-04T00:00:00-04:00"
T2 = "2026-09-04T04:01:00Z"


def snapshot(db):
    return db.execute(
        "SELECT device_id, recorded_at, value, lat, lon, batch_id, source_line "
        "FROM readings ORDER BY device_id, recorded_at"
    ).fetchall()


def counts(db):
    return tuple(db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in ("readings", "batches"))


def test_load_stores_normalized_readings_and_rejections(db, write_csv):
    path = write_csv((" d-0001 ", T1_OFFSET, "NaN", "0", "0"), ("D-0001", "ayer", "1", "", ""))

    parsed, result = load_file(db, path)

    assert (result.inserted, result.updated, result.already_loaded) == (1, 0, False)
    assert db.execute("SELECT device_id, value, lat, lon, source_line FROM readings").fetchone() == (
        "D-0001",
        None,
        None,
        None,
        2,
    )
    assert db.execute("SELECT reason, rows FROM batch_rejections").fetchall() == [("fecha_invalida", 1)]
    assert db.execute("SELECT file_name, rows_read, rows_valid, rows_discarded FROM batches").fetchone() == (
        path.name,
        2,
        1,
        1,
    )
    assert parsed.rows_read == 2


def test_loading_the_same_file_twice_changes_nothing(db, write_csv):
    path = write_csv(("D-0001", T1, "1", "-33.4", "-70.6"))
    load_file(db, path)
    before = snapshot(db), counts(db)

    _, result = load_file(db, path)

    assert result.already_loaded
    assert (snapshot(db), counts(db)) == before


def test_same_content_with_another_name_is_the_same_file(db, write_csv):
    row = ("D-0001", T1, "1", "-33.4", "-70.6")
    load_file(db, write_csv(row, name="a.csv"))

    _, result = load_file(db, write_csv(row, name="b.csv"))

    assert result.already_loaded


def test_later_file_wins_even_with_another_offset(db, write_csv):
    load_file(db, write_csv(("D-0001", T1, "1", "-33.4", "-70.6")))

    _, result = load_file(db, write_csv(("d-0001", T1_OFFSET, "2", "-33.5", "-70.7")))

    assert (result.inserted, result.updated) == (0, 1)
    assert db.execute("SELECT value, lat FROM readings").fetchall() == [(Decimal("2"), -33.5)]


def test_reloading_an_old_file_does_not_revert_a_correction(db, write_csv):
    first = write_csv(("D-0001", T1, "1", "", ""))
    load_file(db, first)
    load_file(db, write_csv(("D-0001", T1, "2", "", "")))
    expected = snapshot(db)

    load_file(db, first)

    assert snapshot(db) == expected


def test_later_row_without_data_replaces_the_whole_reading(db, write_csv):
    load_file(db, write_csv(("D-0001", T1, "1", "-33.4", "-70.6")))

    load_file(db, write_csv(("D-0001", T1, "", "", "")))

    assert db.execute("SELECT value, lat, lon FROM readings").fetchall() == [(None, None, None)]


def test_invalid_row_in_a_later_file_does_not_replace_a_reading(db, write_csv):
    load_file(db, write_csv(("D-0001", T1, "1", "", "")))

    load_file(db, write_csv(("D-0001", T1, "abc", "", ""), ("D-0001", T2, "2", "", "")))

    assert db.execute("SELECT value FROM readings ORDER BY recorded_at").fetchall() == [
        (Decimal("1"),),
        (Decimal("2"),),
    ]


def test_failure_in_the_middle_rolls_back_everything_and_allows_a_retry(db, write_csv, monkeypatch):
    path = write_csv(("D-0001", T1, "1", "", ""), ("D-0001", "ayer", "1", "", ""))
    original = load_module._upsert_readings

    def fail(*_):
        raise RuntimeError("fallo simulado")

    monkeypatch.setattr(load_module, "_upsert_readings", fail)
    with pytest.raises(RuntimeError):
        load_file(db, path)

    assert counts(db) == (0, 0)
    assert db.execute("SELECT count(*) FROM batch_rejections").fetchone()[0] == 0

    monkeypatch.setattr(load_module, "_upsert_readings", original)
    _, result = load_file(db, path)
    assert not result.already_loaded
    assert counts(db) == (1, 1)


def test_summary_has_every_requested_count(db, write_csv):
    path = write_csv(("D-0001", T1, "1", "", ""), ("", T1, "1", "", ""), ("D-0001", "ayer", "1", "", ""))

    summary = format_summary(*load_file(db, path))

    assert "Filas leídas: 3" in summary
    assert "Filas válidas: 1" in summary
    assert "Filas descartadas: 2" in summary
    assert "device_id_vacio: 1" in summary
    assert "fecha_invalida: 1" in summary


def test_command_fails_clearly_when_the_file_does_not_exist(tmp_path, capsys):
    assert load_module.main([str(tmp_path / "no-existe.csv")]) == 1
    assert "No se pudo leer el archivo" in capsys.readouterr().err


def test_command_fails_clearly_with_wrong_columns(tmp_path, capsys):
    path = tmp_path / "malo.csv"
    path.write_text("a,b\n1,2\n", encoding="utf-8")

    assert load_module.main([str(path)]) == 1
    assert "Faltan columnas" in capsys.readouterr().err
