# Excel files bypass docling; native openpyxl/pandas path instead

Excel already provides exact cell values with zero layout-inference risk, unlike PDF where docling's ML models must infer structure from pixels/text positions. Routing `.xlsx`/`.xls` through docling's generic document model would add ML-inference risk for a format that doesn't need it. Excel files are read directly via `openpyxl`/`pandas`, with a gap-based table-region segmentation heuristic per sheet, then mapped into the same `normalized.json` schema as the PDF paths so stage 3 stays format-agnostic.

This decision is about the *format* (Excel has ground-truth cells), not the *complexity* of any given file — it holds regardless of how messy a real "lengthy" Excel sample turns out to be. If the gap-based segmentation heuristic proves too weak for complex multi-table sheets, the fix is a better native heuristic (e.g. reading merged-cell/formatting metadata), not routing through docling.
