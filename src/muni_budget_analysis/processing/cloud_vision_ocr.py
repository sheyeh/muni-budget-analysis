"""
cloud_vision_ocr.py

Custom docling OCR backend: swaps the OCR text-recognition step feeding
docling's TableFormer (scanned-PDF path) from Tesseract to Google Cloud
Vision's DOCUMENT_TEXT_DETECTION -- the hybrid decision locked in by
docs/adr/0001-docling-primary-extraction-engine.md's Status section and
issue #4 (docling keeps table geometry; Cloud Vision only replaces the text
recognizer).

Implements this via docling's real pluggable-OCR surface: a BaseOcrModel +
OcrOptions pair registered with docling.models.factories.get_ocr_factory().
docling/models/stages/ocr/tesseract_ocr_cli_model.py (docling's own
Tesseract backend) is the contract this follows -- one TextCell per
recognized word, per OCR region (`get_ocr_rects`), geometry mapped from the
cropped/scaled OCR image back to page coordinates via
tesseract_box_to_bounding_rectangle (a generic image-to-page geometry
helper despite the name; used with orientation=0 since Vision resolves
text orientation itself, unlike Tesseract which needs a separate OSD pass).

The Vision-call pattern (render page -> PNG -> document_text_detection)
reuses scripts/spike_gcp_ocr.py, which validated Cloud Vision's Hebrew
accuracy on this corpus's scanned samples at 300 DPI.

Auth: Application Default Credentials, same as scripts/spike_gcp_ocr.py --
no credentials are read, printed, or stored here.
"""

from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import ClassVar, Iterable, List, Literal, Type

from docling_core.types.doc import BoundingBox, CoordOrigin
from docling_core.types.doc.page import TextCell
from pydantic import ConfigDict, Field
from typing_extensions import Annotated

from docling.datamodel.accelerator_options import AcceleratorOptions
from docling.datamodel.base_models import Page
from docling.datamodel.document import ConversionResult
from docling.datamodel.pipeline_options import OcrOptions
from docling.models.base_ocr_model import BaseOcrModel
from docling.models.factories import get_ocr_factory
from docling.utils.ocr_utils import tesseract_box_to_bounding_rectangle
from docling.utils.profiling import TimeRecorder

logger = logging.getLogger(__name__)

# Matches scripts/spike_gcp_ocr.py's default -- the resolution the OCR
# comparison spike validated Cloud Vision's Hebrew accuracy at.
_RENDER_DPI = 300


class CloudVisionOcrOptions(OcrOptions):
    """Configuration for the Google Cloud Vision DOCUMENT_TEXT_DETECTION OCR backend."""

    kind: ClassVar[Literal["cloud_vision"]] = "cloud_vision"
    lang: Annotated[
        List[str],
        Field(
            description=(
                "Vision API language hints (BCP-47 codes, e.g. 'he', 'en') -- "
                "passed as image_context.language_hints. Vision auto-detects "
                "script if omitted; hints just bias recognition."
            )
        ),
    ] = ["he", "en"]
    model_config = ConfigDict(extra="forbid")


class CloudVisionOcrModel(BaseOcrModel):
    """docling OCR backend that sends each OCR region to Google Cloud Vision."""

    def __init__(
        self,
        enabled: bool,
        artifacts_path: Path | None,
        options: CloudVisionOcrOptions,
        accelerator_options: AcceleratorOptions,
    ):
        super().__init__(
            enabled=enabled,
            artifacts_path=artifacts_path,
            options=options,
            accelerator_options=accelerator_options,
        )
        self.options: CloudVisionOcrOptions
        self.scale = _RENDER_DPI / 72

        self.client = None
        if self.enabled:
            from google.cloud import vision

            self.client = vision.ImageAnnotatorClient()

    def _ocr_crop(self, high_res_image, ocr_rect: BoundingBox) -> List[TextCell]:
        from google.cloud import vision

        buf = io.BytesIO()
        high_res_image.save(buf, format="PNG")
        image = vision.Image(content=buf.getvalue())
        response = self.client.document_text_detection(
            image=image, image_context={"language_hints": self.options.lang}
        )
        if response.error.message:
            logger.error("Cloud Vision OCR failed: %s", response.error.message)
            return []

        annotation = response.full_text_annotation
        if annotation is None:
            return []

        cells: List[TextCell] = []
        ix = 0
        for page_ann in annotation.pages:
            for block in page_ann.blocks:
                for paragraph in block.paragraphs:
                    for word in paragraph.words:
                        text = "".join(symbol.text for symbol in word.symbols)
                        if not text.strip():
                            continue
                        vertices = word.bounding_box.vertices
                        xs = [v.x for v in vertices]
                        ys = [v.y for v in vertices]
                        word_bbox = BoundingBox(
                            l=min(xs), t=min(ys), r=max(xs), b=max(ys),
                            coord_origin=CoordOrigin.TOPLEFT,
                        )
                        rect = tesseract_box_to_bounding_rectangle(
                            word_bbox,
                            original_offset=ocr_rect,
                            scale=self.scale,
                            orientation=0,
                            im_size=high_res_image.size,
                        )
                        cells.append(
                            TextCell(
                                index=ix,
                                text=text,
                                orig=text,
                                from_ocr=True,
                                confidence=word.confidence,
                                rect=rect,
                            )
                        )
                        ix += 1
        return cells

    def __call__(
        self, conv_res: ConversionResult, page_batch: Iterable[Page]
    ) -> Iterable[Page]:
        if not self.enabled:
            yield from page_batch
            return

        for page in page_batch:
            assert page._backend is not None
            if not page._backend.is_valid():
                yield page
                continue

            with TimeRecorder(conv_res, "ocr"):
                ocr_rects = self.get_ocr_rects(page)
                all_ocr_cells: List[TextCell] = []
                for ocr_rect in ocr_rects:
                    if ocr_rect.area() == 0:
                        continue
                    high_res_image = page._backend.get_page_image(
                        scale=self.scale, cropbox=ocr_rect
                    )
                    all_ocr_cells.extend(self._ocr_crop(high_res_image, ocr_rect))

                self.post_process_cells(all_ocr_cells, page, conv_res)

            yield page

    @classmethod
    def get_options_type(cls) -> Type[OcrOptions]:
        return CloudVisionOcrOptions


def register_cloud_vision_ocr() -> None:
    """
    Register CloudVisionOcrModel with docling's OCR plugin factory.

    Idempotent -- safe to call on every build_ocr_options("cloud_vision").
    Registers into the allow_external_plugins=False factory instance
    specifically: that's the cache key build_pipeline_options() ends up
    using (PdfPipelineOptions.allow_external_plugins defaults to False and
    nothing here changes it), and get_ocr_factory() is @lru_cache'd per that
    flag -- registering into the wrong instance would make this backend
    invisible to the actual conversion run.
    """
    factory = get_ocr_factory(allow_external_plugins=False)
    if CloudVisionOcrOptions in factory.classes:
        return
    factory.register(
        CloudVisionOcrModel,
        plugin_name="muni_budget_analysis",
        plugin_module_name=__name__,
    )
