# ADR 0004: Stage 3 Category Classification, Unit Normalization, and Scope Selection

## Context

Stage 3 (File Analysis and Category Classification) semantically resolves raw, uninterpreted table rows extracted in Stage 2 into structured, well-defined "budget line items" suitable for querying and visualization. It maps row labels to the official Ministry of Interior (MoI) chart of accounts ("ספר קידודים") and infers / normalizes the scale of numeric amounts (units of full NIS vs. thousands of NIS).

Through extensive spike analysis and code revision, we identified several core challenges:
1. **Hebrew Quotation Marks (Gershayim/Quotes)**: Hebrew abbreviations like `ש"ח` (ILS) and `סה"כ` (total) contain quotation marks (`"`), which frequently cause Gemini API JSON outputs to fail parsing under traditional raw-text or regex-based repairs.
2. **Flexible Multipliers**: The original stage 3 pipeline assumed any explicit unit marker meant a unit of `1000` (thousands of NIS), ignoring cases in full NIS or millions.
3. **Percentage Columns**: Percentage-based columns (such as execution-rate percent `ביצוע לעומת תקציב`) were previously treated as standard currency, corrupting numeric aggregations.
4. **Integration with Stage 2.5 (`scoped.json`)**: Level 2.5 identifies the active target year dimension axis (rows or columns) and marks out-of-scope columns or rows with `keep: false`. Stage 3 must filter out these fields to maintain consistency and keep the output clean.
5. **API Quota & Cost Optimization**: Transitioning to standard large models like `gemini-3.6-flash` is too expensive for large batch runs, while smaller models can introduce syntax formatting variances.

---

## Decision

We have implemented the following architectural decisions to fully address these constraints:

### 1. Structured Outputs via Pydantic Schema
To solve the double-quotes parsing issue, Stage 3 now leverages the Gemini API's **Structured Outputs** feature (`response_schema`), passing a precise Pydantic model (`TableClassificationResponse`). 

```python
class RowInference(BaseModel):
    row_index: int = Field(description="The row index of the table being classified.")
    code: Optional[str] = Field(None, description="The matched MoI chart of accounts code, or null if no single specific code applies.")
    row_type: str = Field(description="One of: 'line_item', 'subtotal', or 'grand_total'.")
    confidence: float = Field(description="Confidence rating of the code classification between 0.0 and 1.0.")
    note: str = Field(description="Brief reason for the match/non-match.")
    unusable_input: bool = Field(False, description="Set to True if the input row label is severely malformed, completely garbled, or unusable due to parsing errors.")
```

Enforcing this schema at the API layer ensures the model returns perfectly formatted JSON, natively escaping Gershayim double-quotes.

### 2. Dual-Input Path & Stage 2.5 Alignment
Stage 3 processes `native.json` (layout structure) and optionally reads `scoped.json` (Level 2.5 filtering metadata) in the same subdirectory if it exists. Row-level or column-level slices marked `keep = false` are automatically skipped, ensuring only relevant target fiscal year data is processed.

### 3. Rich Representation for Percentages
Percentage-based values (e.g., matching a `%` symbol or whose column header contains Hebrew percentage terms like `אחוז`, `שיעור`) are:
- Classified with `is_percentage = True`.
- Parsed numerically into `parsed_percentage` (e.g. `105.29`).
- Set to `amount_ils = null` to prevent currency calculation pollution.

### 4. Robust Validation & Garbage Input Flagging
- **Unusable Input Flagging**: The LLM is instructed to flag garbled or malformed rows as `unusable_input = True`.
- **Graceful Omission Handling**: If the LLM omits a row, we set `row_type = "unresolved"`, attach a `validation_warning = "LLM omitted row classification"`, and proceed gracefully rather than crashing the batch.
- **Hallucination Flags**: If the model suggests a code that is not present in the MoI codebook, it is logged with a `Hallucinated code` warning in `validation_warning`.

### 5. Cost-Effective Default Model
We selected **`gemini-3.5-flash-lite`** as the default production model for classification, reducing input costs by 80% ($1.50 -> $0.30/M tokens) and output costs by 72% ($9.00 -> $2.50/M tokens) while maintaining high classification accuracy.

---

## Status

**Accepted and Implemented**. 
Fully covered with comprehensive unit tests (`tests/test_build_output.py`) verifying percentage parsing, validation warnings, unit multiplier mapping, and scope filtering.
