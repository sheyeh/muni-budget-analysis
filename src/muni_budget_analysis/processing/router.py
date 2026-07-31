"""
router.py

Pure decision logic for routing detected budget files to a processing strategy.
No file conversion, no writes -- just decides which extraction path a file
should go through based on its detected type and (for PDFs) whether it has an
extractable text layer.
"""

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def has_text_layer(pdf_path: Path) -> bool:
    """Return True if any page of the PDF has extractable text."""
    import pypdf

    reader = pypdf.PdfReader(str(pdf_path))
    for page in reader.pages:
        text = (page.extract_text() or "").strip()
        if len(text) > 0:
            return True
    return False


def route(detected_type: str, local_path: Path) -> Optional[str]:
    """
    Decide which processing strategy applies to a downloaded file.

    detected_type is expected to be one of {"pdf", "xlsx", "xls", "unknown"}
    (ingest.py's Task 3 output vocabulary).
    """
    if detected_type == "pdf":
        if has_text_layer(local_path):
            return "docling_pdf"
        return "docling_pdf_ocr"
    if detected_type in ("xlsx", "xls"):
        return "excel_native"
    logger.info("No route for detected_type=%s (%s)", detected_type, local_path)
    return None
