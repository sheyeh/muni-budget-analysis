"""
Level-2 file processing pipeline: manifest, ingest, routing, PDF/Excel conversion, normalization.
"""

from .excel_pipeline import extract_excel_tables
from .ingest import ingest
from .manifest import build_manifest_record, read_manifest, write_manifest
from .normalize import excel_to_normalized, pdf_result_to_normalized, write_normalized
from .pdf_pipeline import convert_pdf, convert_pdf_with_document, dump_markdown, dump_native_json, get_docling_version
from .router import route

# .run must be imported last: run.py does `from . import excel_pipeline,
# manifest, normalize, pdf_pipeline, router` at module scope, which relies
# on those already being bound as attributes on this partially-initialized
# package -- true only because nothing after this import runs first.
from .run import load_level1_manifest, main, process_one, run_batch

__all__ = [
    "extract_excel_tables",
    "ingest",
    "build_manifest_record",
    "read_manifest",
    "write_manifest",
    "excel_to_normalized",
    "pdf_result_to_normalized",
    "write_normalized",
    "convert_pdf",
    "convert_pdf_with_document",
    "dump_markdown",
    "dump_native_json",
    "get_docling_version",
    "route",
    "load_level1_manifest",
    "main",
    "process_one",
    "run_batch",
]
