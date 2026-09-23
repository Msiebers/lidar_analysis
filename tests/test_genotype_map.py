from __future__ import annotations

from pathlib import Path

import pytest

from lidar_analysis.genotype_map import load_genotype_map


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_successful_whole_plot_mapping(tmp_path):
    csv_path = _write(
        tmp_path / "map.csv",
        "experiment,plot,genotype_id,notes\n"
        "MeadowFescue,1,MF001,\n",
    )
    result = load_genotype_map(csv_path, "MeadowFescue")
    assert result.genotype_for("1") == "MF001"
    assert result.experiment_rows == 1
    assert result.total_rows == 1


def test_multiple_plots_different_genotypes(tmp_path):
    csv_path = _write(
        tmp_path / "map.csv",
        "experiment,plot,genotype_id,notes\n"
        "MeadowFescue,1,MF001,\n"
        "MeadowFescue,2,MF017,\n"
        "MeadowFescue,3,MF042,\n",
    )
    result = load_genotype_map(csv_path, "MeadowFescue")
    assert result.genotype_for("1") == "MF001"
    assert result.genotype_for("2") == "MF017"
    assert result.genotype_for("3") == "MF042"
    assert result.experiment_rows == 3


def test_plot_is_never_int_coerced(tmp_path):
    # A non-numeric plot identifier, matching what the real pipeline can
    # actually produce (e.g. "plant_1"), must round-trip untouched.
    csv_path = _write(
        tmp_path / "map.csv",
        "experiment,plot,genotype_id,notes\n"
        "MeadowFescue,plant_1,MF001,\n"
        "MeadowFescue,01,MF002,\n",  # looks like it could collide with "1" if coerced
    )
    result = load_genotype_map(csv_path, "MeadowFescue")
    assert result.genotype_for("plant_1") == "MF001"
    assert result.genotype_for("01") == "MF002"
    assert result.genotype_for("1") is None  # "1" != "01" as strings, by design
    assert result.genotype_for(" plant_1 ") == "MF001"  # whitespace is stripped


def test_missing_mapping_returns_none(tmp_path):
    csv_path = _write(
        tmp_path / "map.csv",
        "experiment,plot,genotype_id,notes\n"
        "MeadowFescue,1,MF001,\n",
    )
    result = load_genotype_map(csv_path, "MeadowFescue")
    assert result.genotype_for("99") is None


def test_duplicate_experiment_plot_raises(tmp_path):
    csv_path = _write(
        tmp_path / "map.csv",
        "experiment,plot,genotype_id,notes\n"
        "MeadowFescue,1,MF001,\n"
        "MeadowFescue,1,MF999,\n",
    )
    with pytest.raises(ValueError, match="duplicate mapping"):
        load_genotype_map(csv_path, "MeadowFescue")


def test_duplicate_even_with_identical_genotype_id_raises(tmp_path):
    # A repeated row is still a data error worth catching, even if it would
    # not itself corrupt the join.
    csv_path = _write(
        tmp_path / "map.csv",
        "experiment,plot,genotype_id,notes\n"
        "MeadowFescue,1,MF001,\n"
        "MeadowFescue,1,MF001,\n",
    )
    with pytest.raises(ValueError, match="duplicate mapping"):
        load_genotype_map(csv_path, "MeadowFescue")


def test_empty_genotype_id_raises(tmp_path):
    csv_path = _write(
        tmp_path / "map.csv",
        "experiment,plot,genotype_id,notes\n"
        "MeadowFescue,1,,\n",
    )
    with pytest.raises(ValueError, match="genotype_id is blank"):
        load_genotype_map(csv_path, "MeadowFescue")


def test_blank_experiment_raises(tmp_path):
    csv_path = _write(
        tmp_path / "map.csv",
        "experiment,plot,genotype_id,notes\n"
        ",1,MF001,\n",
    )
    with pytest.raises(ValueError, match="experiment is blank"):
        load_genotype_map(csv_path, "MeadowFescue")


def test_blank_plot_raises(tmp_path):
    csv_path = _write(
        tmp_path / "map.csv",
        "experiment,plot,genotype_id,notes\n"
        "MeadowFescue,,MF001,\n",
    )
    with pytest.raises(ValueError, match="plot is blank"):
        load_genotype_map(csv_path, "MeadowFescue")


def test_genotype_id_is_opaque_and_permissive(tmp_path):
    """genotype_id is biological metadata, not a filename -- spaces, slashes,
    parentheses, colons and other characters a real naming scheme might use
    must be accepted and preserved exactly, not rejected or normalized.
    This replaces a previous version of this test that asserted the
    opposite (a restrictive character allowlist); that restriction was a
    filename-safety convention that never applied to genotype_id and was
    removed as a deliberate design decision, not weakened to pass."""
    csv_path = _write(
        tmp_path / "map.csv",
        'experiment,plot,genotype_id,notes\n'
        'MeadowFescue,1,"MF 001 (tall fescue / early)",\n'
        "MeadowFescue,2,MF:cultivar-42,\n",
    )
    result = load_genotype_map(csv_path, "MeadowFescue")
    assert result.genotype_for("1") == "MF 001 (tall fescue / early)"
    assert result.genotype_for("2") == "MF:cultivar-42"


def test_genotype_id_whitespace_stripped_but_internal_text_preserved(tmp_path):
    csv_path = _write(
        tmp_path / "map.csv",
        "experiment,plot,genotype_id,notes\n"
        'MeadowFescue,1,"  MF 001  ",\n',  # leading/trailing spaces around, internal space kept
    )
    result = load_genotype_map(csv_path, "MeadowFescue")
    assert result.genotype_for("1") == "MF 001"  # outer whitespace gone, internal space kept


def test_genotype_id_case_is_never_folded(tmp_path):
    csv_path = _write(
        tmp_path / "map.csv",
        "experiment,plot,genotype_id,notes\n"
        "MeadowFescue,1,Mf-Mixed-Case,\n",
    )
    result = load_genotype_map(csv_path, "MeadowFescue")
    assert result.genotype_for("1") == "Mf-Mixed-Case"  # not upper()'d or lower()'d


def test_csv_quoting_round_trips_commas_and_quotes_in_notes_and_genotype_id(tmp_path):
    # A genotype_id and a notes field each containing a comma and an
    # embedded double quote, written using standard CSV quoting rules
    # (RFC 4180: wrap in quotes, double any embedded quote).
    csv_path = _write(
        tmp_path / "map.csv",
        "experiment,plot,genotype_id,notes\n"
        'MeadowFescue,1,"MF,001 ""tall""","note, with a comma and a ""quoted"" word"\n',
    )
    result = load_genotype_map(csv_path, "MeadowFescue")
    assert result.genotype_for("1") == 'MF,001 "tall"'
    assert result.notes_by_plot["1"] == 'note, with a comma and a "quoted" word'


def test_missing_required_column_raises(tmp_path):
    csv_path = _write(
        tmp_path / "map.csv",
        "experiment,plot,notes\n"
        "MeadowFescue,1,some note\n",
    )
    with pytest.raises(ValueError, match="missing required column"):
        load_genotype_map(csv_path, "MeadowFescue")


def test_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_genotype_map(tmp_path / "does_not_exist.csv", "MeadowFescue")


def test_wrong_experiment_rows_excluded_but_still_checked_for_duplicates(tmp_path):
    csv_path = _write(
        tmp_path / "map.csv",
        "experiment,plot,genotype_id,notes\n"
        "MeadowFescue,1,MF001,\n"
        "OtherTrial,1,OT999,\n",  # same plot number, different experiment: fine
    )
    result = load_genotype_map(csv_path, "MeadowFescue")
    assert result.genotype_for("1") == "MF001"
    assert result.experiment_rows == 1
    assert result.total_rows == 2

    other = load_genotype_map(csv_path, "OtherTrial")
    assert other.genotype_for("1") == "OT999"
    assert other.experiment_rows == 1


def test_unused_plots(tmp_path):
    csv_path = _write(
        tmp_path / "map.csv",
        "experiment,plot,genotype_id,notes\n"
        "MeadowFescue,1,MF001,\n"
        "MeadowFescue,2,MF017,\n"
        "MeadowFescue,42,MF999,not scanned yet\n",
    )
    result = load_genotype_map(csv_path, "MeadowFescue")
    assert result.unused_plots({"1", "2"}) == ["42"]
    assert result.unused_plots({"1", "2", "42"}) == []


def test_hash_is_stable_for_same_content(tmp_path):
    csv_path = _write(
        tmp_path / "map.csv",
        "experiment,plot,genotype_id,notes\n"
        "MeadowFescue,1,MF001,\n",
    )
    first = load_genotype_map(csv_path, "MeadowFescue")
    second = load_genotype_map(csv_path, "MeadowFescue")
    assert first.sha256 == second.sha256
    assert len(first.sha256) == 64
