"""
run.py

Batch entrypoint for the level-2 file processing pipeline (Task 7): for each
record in a level-1 manifest, run ingest -> route -> convert -> normalize ->
persist, writing processed/{muni_id}/{filename_stem}/{manifest.json,
normalized.json, docling_native.json, document.md}.

Sequential, single-process -- no worker pool, per prd.md ("no SLA, avoid
speculative complexity"). A failed/partial file must never crash the batch:
process_one() wraps its entire happy path in a try/except and always returns
a manifest record (never raises).
"""

import argparse
import logging
from pathlib import Path
from typing import Any, Dict, List

from docling.datamodel.pipeline_options import TableFormerMode

# `from . import <module>` here relies on processing/__init__.py having
# already bound these as package attributes -- true only because
# __init__.py imports `.run` last (see the comment there). Don't reorder
# that block without checking this still holds.
from . import excel_pipeline, manifest, normalize, pdf_pipeline, router
# NOTE: imported directly (not `from . import ingest`) because ingest.py's
# module name collides with its own primary export name -- processing/__init__.py's
# `from .ingest import ingest` rebinds the package's `ingest` attribute to the
# function, so `from . import ingest` here would silently resolve to the
# function object, not the module, once __init__.py has run.
from .ingest import ingest as ingest_file

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_RAW_DIR = PROJECT_ROOT / "data" / "raw"
DEFAULT_PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"

# Table extraction mode used for batch runs. ACCURATE is docling's slower,
# higher-fidelity TableFormer mode; prd.md doesn't ask for a configurable
# mode at this stage, so it's hardcoded here rather than threaded through
# run_batch()/process_one()/main() as a speculative parameter. Tests that
# want a fast dev-loop (tests/test_run_e2e.py) override table_mode by
# monkeypatching this constant.
TABLE_MODE = TableFormerMode.ACCURATE

NATIVE_JSON_FILENAME = "docling_native.json"
MARKDOWN_FILENAME = "document.md"


def load_level1_manifest(path: Path) -> List[Dict[str, Any]]:
    """Load a level-1 manifest: a JSON array of {muni_id, budget_filename, source} records."""
    import json

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def process_one(record: Dict[str, Any], raw_dir: Path, processed_dir: Path) -> Dict[str, Any]:
    """
    Run one level-1 record through ingest -> route -> convert -> normalize ->
    persist, and return its manifest record. Never raises -- any exception
    is caught, logged, and turned into a status="failed" manifest record
    (per prd.md: a failed/partial file must not crash the batch).
    """
    muni_id = record.get("muni_id")
    source_filename = record.get("budget_filename")

    # Tracked so a failure partway through still reports whatever was
    # determined before the exception, per the task spec.
    source_sha256 = None
    detected_type = None
    pipeline_used = None
    docling_version = None
    page_count = None
    # Derived from the record alone (budget_filename's stem needs no file
    # access), so it's known even if ingest() itself fails below -- letting
    # the except branch still write the failed manifest to the right place.
    file_processed_dir = (
        processed_dir / str(muni_id) / Path(source_filename).stem
        if muni_id is not None and source_filename
        else None
    )

    try:
        ingested = ingest_file(record, raw_dir, processed_dir)
        source_sha256 = ingested["source_sha256"]
        detected_type = ingested["detected_type"]
        file_processed_dir = processed_dir / str(muni_id) / ingested["filename_stem"]

        if ingested["skip"]:
            existing = manifest.read_manifest(file_processed_dir)
            if existing is not None:
                logger.info(
                    "Already processed (unchanged content hash), skipping: muni_id=%s file=%s",
                    muni_id, source_filename,
                )
                return existing
            # TOCTOU edge case: is_already_processed() (inside ingest())
            # found a manifest moments ago but it's gone now -- fall through
            # and reprocess instead of returning None, which would break
            # process_one's "always returns a manifest record" contract and
            # crash run_batch's summary loop on a NoneType.
            logger.warning(
                "Manifest disappeared between skip-check and read, reprocessing: "
                "muni_id=%s file=%s", muni_id, source_filename,
            )

        pipeline_used = router.route(detected_type, ingested["local_path"])
        if pipeline_used is None:
            warnings = [f"unsupported file type: {detected_type}"]
            record_out = manifest.build_manifest_record(
                muni_id=muni_id,
                source_filename=source_filename,
                source_sha256=source_sha256,
                detected_type=detected_type,
                pipeline_used=None,
                docling_version=None,
                page_count=None,
                warnings=warnings,
                outputs={},
            )
            manifest.write_manifest(file_processed_dir, record_out)
            return record_out

        outputs: Dict[str, str] = {}

        if pipeline_used in ("docling_pdf", "docling_pdf_ocr"):
            docling_version = pdf_pipeline.get_docling_version()
            pdf_result, doc = pdf_pipeline.convert_pdf_with_document(
                ingested["local_path"], pipeline_used=pipeline_used, table_mode=TABLE_MODE
            )
            page_count = pdf_result["page_count"]
            normalized = normalize.pdf_result_to_normalized(
                pdf_result, muni_id, source_filename, pipeline_used
            )

            # docling_native.json / document.md are dumped from the SAME
            # `doc` object convert_pdf_with_document() already produced --
            # no second conversion of the PDF (see pdf_pipeline.py's
            # convert_pdf_with_document docstring for the design rationale).
            # Any failure here is caught by process_one's outer try/except
            # like every other step, per the task spec (no extra inner
            # resilience invented beyond what was asked for).
            file_processed_dir.mkdir(parents=True, exist_ok=True)
            pdf_pipeline.dump_native_json(doc, file_processed_dir / NATIVE_JSON_FILENAME)
            outputs["docling_native"] = NATIVE_JSON_FILENAME

            pdf_pipeline.dump_markdown(doc, file_processed_dir / MARKDOWN_FILENAME)
            outputs["markdown"] = MARKDOWN_FILENAME

        elif pipeline_used == "excel_native":
            excel_result = excel_pipeline.extract_excel_tables(ingested["local_path"])
            normalized = normalize.excel_to_normalized(excel_result, muni_id, source_filename)

        else:
            raise ValueError(f"Unhandled pipeline_used: {pipeline_used!r}")

        normalize.write_normalized(file_processed_dir, normalized)
        outputs["normalized"] = normalize.NORMALIZED_FILENAME

        warnings: List[str] = []  # no warning-producing conditions defined yet

        record_out = manifest.build_manifest_record(
            muni_id=muni_id,
            source_filename=source_filename,
            source_sha256=source_sha256,
            detected_type=detected_type,
            pipeline_used=pipeline_used,
            docling_version=docling_version,
            page_count=page_count,
            warnings=warnings,
            outputs=outputs,
        )
        manifest.write_manifest(file_processed_dir, record_out)
        logger.info(
            "Processed muni_id=%s file=%s pipeline=%s status=%s",
            muni_id, source_filename, pipeline_used, record_out["status"],
        )
        return record_out

    except Exception as exc:
        logger.exception("Failed to process muni_id=%s file=%s", muni_id, source_filename)
        record_out = manifest.build_manifest_record(
            muni_id=muni_id,
            source_filename=source_filename,
            source_sha256=source_sha256,
            detected_type=detected_type,
            pipeline_used=pipeline_used,
            docling_version=docling_version,
            page_count=page_count,
            warnings=[],
            outputs={},
            error=str(exc),
        )
        if file_processed_dir is not None:
            try:
                manifest.write_manifest(file_processed_dir, record_out)
            except Exception:
                # Persisting the failure manifest itself failed (e.g. disk
                # error) -- log and still honor process_one's "never raises"
                # contract; the caller gets the in-memory record_out either way.
                logger.exception(
                    "Failed to write failure manifest for muni_id=%s file=%s",
                    muni_id, source_filename,
                )
        return record_out


def run_batch(
    level1_manifest_path: Path, raw_dir: Path, processed_dir: Path
) -> List[Dict[str, Any]]:
    """Process every record in a level-1 manifest sequentially, collecting manifest records."""
    records = load_level1_manifest(level1_manifest_path)
    logger.info("Loaded %d record(s) from %s", len(records), level1_manifest_path)

    results: List[Dict[str, Any]] = []
    for record in records:
        results.append(process_one(record, raw_dir, processed_dir))

    status_counts: Dict[str, int] = {}
    for result in results:
        status = result.get("status", "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1

    print("\n=== Level-2 Batch Processing Complete ===")
    print(f"Total Files Processed: {len(results)}")
    for status in ("success", "partial", "failed"):
        print(f"  {status}: {status_counts.get(status, 0)}")

    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the level-2 file processing pipeline over a level-1 manifest"
    )
    parser.add_argument(
        "--level1-manifest",
        type=Path,
        required=True,
        help="Path to a level-1 manifest JSON file (array of {muni_id, budget_filename, source})",
    )
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=DEFAULT_RAW_DIR,
        help=f"Directory for raw downloaded/staged source files (default: {DEFAULT_RAW_DIR})",
    )
    parser.add_argument(
        "--processed-dir",
        type=Path,
        default=DEFAULT_PROCESSED_DIR,
        help=f"Directory for processed outputs (default: {DEFAULT_PROCESSED_DIR})",
    )

    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    run_batch(args.level1_manifest, args.raw_dir, args.processed_dir)


if __name__ == "__main__":
    main()
