import importlib.util
from pathlib import Path

import pypdf
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# scripts/ has no __init__.py, so these are loaded directly by file path
# rather than via sys.path insertion (no existing precedent for importing
# from scripts/ in tests/).
build_level1_manifest = _load_module(
    REPO_ROOT / "scripts" / "build_level1_manifest.py", "build_level1_manifest"
)
run_scope_classify = _load_module(
    REPO_ROOT / "scripts" / "run_scope_classify.py", "run_scope_classify"
)


def test_parse_muni_dirname_valid():
    assert build_level1_manifest.parse_muni_dirname("32_מועצה_אזורית_גדרות") == (
        32,
        "מועצה_אזורית_גדרות",
    )


def test_parse_muni_dirname_invalid():
    with pytest.raises(ValueError):
        build_level1_manifest.parse_muni_dirname("general")


def _make_year_file(muni_dir: Path, year: str, filename: str) -> Path:
    year_dir = muni_dir / year
    year_dir.mkdir(parents=True, exist_ok=True)
    file_path = year_dir / filename
    file_path.write_bytes(b"pdf-bytes")
    return file_path


def test_discover_year_records_single_file_per_year_skips_general_and_ds_store(tmp_path):
    data_dir = tmp_path / "data"
    muni_dir = data_dir / "32_מועצה_אזורית_גדרות"
    _make_year_file(muni_dir, "2018", "1541058045.2762.pdf")
    (muni_dir / "2018" / ".DS_Store").write_bytes(b"")

    general_dir = muni_dir / "general"
    general_dir.mkdir()
    (general_dir / "1767188161.5613.pdf").write_bytes(b"pdf-bytes")

    records, skipped = build_level1_manifest.discover_year_records(data_dir)

    assert skipped == []
    assert len(records) == 1
    record = records[0]
    assert record["muni_id"] == 32
    assert record["muni_dir_name"] == "32_מועצה_אזורית_גדרות"
    assert record["year"] == 2018
    assert record["file_path"].name == "1541058045.2762.pdf"


def test_discover_year_records_multi_file_skips_with_warning(tmp_path, caplog):
    data_dir = tmp_path / "data"
    year_dir = data_dir / "1_test_muni" / "2020"
    year_dir.mkdir(parents=True)
    (year_dir / "a.pdf").write_bytes(b"a")
    (year_dir / "b.pdf").write_bytes(b"b")

    with caplog.at_level("WARNING"):
        records, skipped = build_level1_manifest.discover_year_records(data_dir)

    assert records == []
    assert len(skipped) == 1
    assert skipped[0]["muni_id"] == 1
    assert skipped[0]["year"] == 2020
    assert set(skipped[0]["file_names"]) == {"a.pdf", "b.pdf"}
    assert "needs manual resolution" in caplog.text


def _make_pdf(path: Path, num_pages: int = 1) -> Path:
    writer = pypdf.PdfWriter()
    for _ in range(num_pages):
        writer.add_blank_page(width=72, height=72)
    with open(path, "wb") as f:
        writer.write(f)
    return path


def test_select_multi_file_candidate_merges_part_files(tmp_path):
    year_dir = tmp_path / "5000_תל_אביב_-יפו" / "2009"
    year_dir.mkdir(parents=True)
    # out of numeric order on purpose
    files = [
        _make_pdf(year_dir / "תקציב העירייה לשנת 2009 - תקציב רגיל-חלק 3.pdf"),
        _make_pdf(year_dir / "תקציב העירייה לשנת 2009 - תקציב רגיל-חלק 1.pdf"),
        _make_pdf(year_dir / "תקציב העירייה לשנת 2009 - תקציב רגיל-חלק 2.pdf"),
    ]
    merged_dir = tmp_path / "data_merged"

    result = build_level1_manifest.select_multi_file_candidate(
        files, "5000_תל_אביב_-יפו", 2009, merged_dir
    )

    assert result == merged_dir / "5000_תל_אביב_-יפו_2009-merged.pdf"
    assert len(pypdf.PdfReader(result).pages) == 3


def test_select_multi_file_candidate_merge_is_idempotent(tmp_path):
    year_dir = tmp_path / "5000_תל_אביב_-יפו" / "2009"
    year_dir.mkdir(parents=True)
    files = [
        _make_pdf(year_dir / "חלק 1.pdf"),
        _make_pdf(year_dir / "חלק 2.pdf"),
    ]
    merged_dir = tmp_path / "data_merged"

    first = build_level1_manifest.select_multi_file_candidate(
        files, "5000_תל_אביב_-יפו", 2009, merged_dir
    )
    first_mtime = first.stat().st_mtime
    second = build_level1_manifest.select_multi_file_candidate(
        files, "5000_תל_אביב_-יפו", 2009, merged_dir
    )

    assert second == first
    assert second.stat().st_mtime == first_mtime


def test_select_multi_file_candidate_prefers_full_over_summary_sikumim(tmp_path):
    year_dir = tmp_path / "5000_תל_אביב_-יפו" / "2013"
    year_dir.mkdir(parents=True)
    full = year_dir / "תקציב העירייה הרגיל לשנת 2013.xls"
    full.write_bytes(b"full")
    summary = year_dir / "תקציב העירייה הרגיל לשנת 2013 - סיכומים.xls"
    summary.write_bytes(b"summary")

    result = build_level1_manifest.select_multi_file_candidate(
        [full, summary], "5000_תל_אביב_-יפו", 2013, tmp_path / "data_merged"
    )

    assert result == full


def test_select_multi_file_candidate_prefers_full_over_summary_tamzit(tmp_path):
    year_dir = tmp_path / "6600_חולון" / "2011"
    year_dir.mkdir(parents=True)
    summary = year_dir / "תמצית תקציב רגיל לשנת 2011.pdf"
    summary.write_bytes(b"summary")
    full = year_dir / "תקציב רגיל לשנת 2011.xls"
    full.write_bytes(b"full")

    result = build_level1_manifest.select_multi_file_candidate(
        [summary, full], "6600_חולון", 2011, tmp_path / "data_merged"
    )

    assert result == full


def test_select_multi_file_candidate_prefers_excel_over_pdf_companions(tmp_path):
    year_dir = tmp_path / "5000_תל_אביב_-יפו" / "2022"
    year_dir.mkdir(parents=True)
    full_xlsx = year_dir / "תקציב העירייה הרגיל לשנת 2022.xlsx"
    full_xlsx.write_bytes(b"full")
    summary_xlsx = year_dir / "תקציב העירייה הרגיל לשנת 2022 - סיכומים.xlsx"
    summary_xlsx.write_bytes(b"summary")
    notes_pdf = year_dir / "דברי הסבר הצעת תקציב רגיל 2022.pdf"
    notes_pdf.write_bytes(b"notes")
    book_pdf = year_dir / "ספר תקציב רגיל - פירוט 2022.pdf"
    book_pdf.write_bytes(b"book")

    result = build_level1_manifest.select_multi_file_candidate(
        [full_xlsx, summary_xlsx, notes_pdf, book_pdf],
        "5000_תל_אביב_-יפו", 2022, tmp_path / "data_merged",
    )

    assert result == full_xlsx


def test_select_multi_file_candidate_prefers_updated_variant(tmp_path):
    year_dir = tmp_path / "6600_חולון" / "2017"
    year_dir.mkdir(parents=True)
    original = year_dir / "תקציב רגיל 2017.xls"
    original.write_bytes(b"original")
    updated = year_dir / "תקציב רגיל מעודכן 2017.xls"
    updated.write_bytes(b"updated")

    result = build_level1_manifest.select_multi_file_candidate(
        [original, updated], "6600_חולון", 2017, tmp_path / "data_merged"
    )

    assert result == updated


def test_select_multi_file_candidate_returns_none_when_still_ambiguous(tmp_path):
    year_dir = tmp_path / "5000_תל_אביב_-יפו" / "2020"
    year_dir.mkdir(parents=True)
    excel_a = year_dir / "תקציב העירייה הרגיל לשנת 2020 אקסל.xls"
    excel_a.write_bytes(b"a")
    excel_b = year_dir / "תקציב העירייה הרגיל לשנת 2020.xlsx"
    excel_b.write_bytes(b"b")
    notes_pdf = year_dir / "דברי הסבר הצעת תקציב רגיל 2020.pdf"
    notes_pdf.write_bytes(b"notes")

    result = build_level1_manifest.select_multi_file_candidate(
        [excel_a, excel_b, notes_pdf], "5000_תל_אביב_-יפו", 2020, tmp_path / "data_merged"
    )

    assert result is None


def test_discover_year_records_multi_file_auto_resolves_and_reports_fewer_skips(tmp_path, caplog):
    data_dir = tmp_path / "data"
    merged_dir = tmp_path / "data_merged"

    resolvable_dir = data_dir / "6600_חולון" / "2011"
    resolvable_dir.mkdir(parents=True)
    (resolvable_dir / "תמצית תקציב רגיל לשנת 2011.pdf").write_bytes(b"summary")
    full = resolvable_dir / "תקציב רגיל לשנת 2011.xls"
    full.write_bytes(b"full")

    ambiguous_dir = data_dir / "5000_תל_אביב_-יפו" / "2020"
    ambiguous_dir.mkdir(parents=True)
    (ambiguous_dir / "תקציב העירייה הרגיל לשנת 2020 אקסל.xls").write_bytes(b"a")
    (ambiguous_dir / "תקציב העירייה הרגיל לשנת 2020.xlsx").write_bytes(b"b")

    with caplog.at_level("WARNING"):
        records, skipped = build_level1_manifest.discover_year_records(data_dir, merged_dir)

    assert len(records) == 1
    assert records[0]["muni_id"] == 6600
    assert records[0]["file_path"] == full

    assert len(skipped) == 1
    assert skipped[0]["muni_id"] == 5000
    assert skipped[0]["year"] == 2020


def test_load_csv_index_match_and_year_zero_excluded(tmp_path):
    csv_path = tmp_path / "budget_files.csv"
    header = (
        "municipality_code,municipality_name,municipality_type,website_url,"
        "budget_year,file_type,download_success,downloaded_path,file_size_bytes,"
        "source_url,link_text\n"
    )
    rows = (
        "32,מועצה אזורית גדרות,מועצה אזורית,http://example.com,2018,pdf,True,"
        "data/budgets/32/2018/x.pdf,100,http://example.com/x.pdf,budget\n"
        "1,No Year Muni,עירייה,http://example.com,0,pdf,True,"
        "data/budgets/1/general/y.pdf,50,http://example.com/y.pdf,budget\n"
    )
    csv_path.write_bytes(("﻿" + header + rows).encode("utf-8"))

    index = build_level1_manifest.load_csv_index(csv_path)

    assert set(index) == {(32, 2018)}
    assert index[(32, 2018)]["municipality_name"] == "מועצה אזורית גדרות"


def test_build_manifest_record_filename_roundtrips_extract_year(tmp_path):
    repo_root = tmp_path.resolve()
    file_path = repo_root / "data" / "32_מועצה_אזורית_גדרות" / "2018" / "1541058045.2762.pdf"
    file_path.parent.mkdir(parents=True)
    file_path.write_bytes(b"pdf-bytes")

    record = build_level1_manifest.build_manifest_record(
        muni_id=32,
        muni_dir_name="32_מועצה_אזורית_גדרות",
        year=2018,
        file_path=file_path,
        repo_root=repo_root,
        csv_index={},
    )

    assert record["muni_id"] == 32
    assert record["source"] == {
        "kind": "local",
        "value": "data/32_מועצה_אזורית_גדרות/2018/1541058045.2762.pdf",
    }
    assert run_scope_classify.extract_year(record["budget_filename"]) == 2018


def test_build_manifest_record_falls_back_to_absolute_path_outside_repo_root(tmp_path):
    repo_root = (tmp_path / "repo").resolve()
    repo_root.mkdir()
    file_path = tmp_path / "outside" / "1_test_muni" / "2020" / "f.pdf"
    file_path.parent.mkdir(parents=True)
    file_path.write_bytes(b"x")

    record = build_level1_manifest.build_manifest_record(
        muni_id=1,
        muni_dir_name="1_test_muni",
        year=2020,
        file_path=file_path,
        repo_root=repo_root,
        csv_index={},
    )

    assert record["source"] == {"kind": "local", "value": str(file_path.resolve())}


def test_build_manifest_record_pre_2000_year_still_included_with_warning(tmp_path, caplog):
    repo_root = tmp_path.resolve()
    file_path = repo_root / "data" / "565_אזור" / "1996" / "old.pdf"
    file_path.parent.mkdir(parents=True)
    file_path.write_bytes(b"x")

    with caplog.at_level("WARNING"):
        record = build_level1_manifest.build_manifest_record(
            muni_id=565,
            muni_dir_name="565_אזור",
            year=1996,
            file_path=file_path,
            repo_root=repo_root,
            csv_index={},
        )

    assert record["budget_filename"] == "565_אזור_1996.pdf"
    assert "pre-2000" in caplog.text
    # extract_year() genuinely can't recover this year -- that's the point of the warning
    assert run_scope_classify.extract_year(record["budget_filename"]) is None


def test_build_manifest_record_enrichment_from_csv_match(tmp_path):
    repo_root = tmp_path.resolve()
    file_path = repo_root / "data" / "1_test_muni" / "2020" / "f.pdf"
    file_path.parent.mkdir(parents=True)
    file_path.write_bytes(b"x")
    csv_index = {
        (1, 2020): {
            "municipality_name": "Test Muni",
            "municipality_type": "עירייה",
            "website_url": "http://example.com",
        }
    }

    record = build_level1_manifest.build_manifest_record(
        muni_id=1,
        muni_dir_name="1_test_muni",
        year=2020,
        file_path=file_path,
        repo_root=repo_root,
        csv_index=csv_index,
    )

    assert record["municipality_name"] == "Test Muni"
    assert record["municipality_type"] == "עירייה"
    assert record["website_url"] == "http://example.com"


def test_build_manifest_record_no_csv_match_omits_enrichment(tmp_path):
    repo_root = tmp_path.resolve()
    file_path = repo_root / "data" / "1_test_muni" / "2020" / "f.pdf"
    file_path.parent.mkdir(parents=True)
    file_path.write_bytes(b"x")

    record = build_level1_manifest.build_manifest_record(
        muni_id=1,
        muni_dir_name="1_test_muni",
        year=2020,
        file_path=file_path,
        repo_root=repo_root,
        csv_index={},
    )

    assert "municipality_name" not in record
    assert "municipality_type" not in record
    assert "website_url" not in record
