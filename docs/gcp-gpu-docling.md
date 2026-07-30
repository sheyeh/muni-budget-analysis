# Running docling on a GCP GPU VM

## Why

Docling's layout model and TableFormer (table-structure) model are both
PyTorch models. On CPU, ACCURATE-mode conversion of `even_yehuda_2025.pdf`
(1 page) took **78.7s**. Extrapolated to `tel_aviv_2026.pdf` (364 pages),
that's multiple hours — not workable for iterating on the pipeline, and
not something to run inline in Task 5/7's batch job.

On a spot **NVIDIA T4** GPU, the same 364-page file, same ACCURATE mode,
converted in **1053.1s (~17.5 min)**, with all 353 tables extracted and
zero errors. Table fidelity check passed: code `631` landed as
`19,640,900 / 20,000,000 / 20,000,000` in separate cells, matching the
PRD Task 0 acceptance criterion exactly. Full output in
`docs/examples/docling/tel_aviv_2026/`.

**Conclusion: GPU is worth it for any full-corpus (~200 file) batch run
(Task 7), and for iterating on large PDFs during development.** It is not
needed for the small samples (1-4pp) — those run fine on CPU in seconds.

## How to reproduce (or run a bigger batch)

Use `scripts/gcp_gpu_spike.sh`. It wraps the exact steps below as
subcommands.

```bash
export GCP_PROJECT=your-project-id   # must have GPU quota, see below
scripts/gcp_gpu_spike.sh create
scripts/gcp_gpu_spike.sh bootstrap
scripts/gcp_gpu_spike.sh upload scripts/spike_docling.py
scripts/gcp_gpu_spike.sh upload budget_examples/tel_aviv_2026.pdf
scripts/gcp_gpu_spike.sh run --only tel_aviv_2026 --device cuda
scripts/gcp_gpu_spike.sh download docs/examples/docling/tel_aviv_2026/native.json /tmp/native.json
scripts/gcp_gpu_spike.sh download docs/examples/docling/tel_aviv_2026/document.md /tmp/document.md
scripts/gcp_gpu_spike.sh delete    # do this -- it's billed by the hour
```

`spike_docling.py` gained a `--device {auto,cpu,cuda}` flag for this
(default `auto`, which is docling's own default behavior — it already
picks CUDA automatically if `torch.cuda.is_available()`). The explicit
flag exists so a run's log states which device it actually used.

### What the VM looks like

- Image: `pytorch-2-9-cu129-ubuntu-2204-nvidia-580` (project `ml-images`)
  — Google's Deep Learning VM image, CUDA/cuDNN/driver/PyTorch
  preinstalled, saves ~15 min of driver-install fuss per VM.
- Machine: `n1-standard-4` + 1x `nvidia-tesla-t4` (T4 quota is commonly
  available by default, unlike A100/L4 which may need a quota request).
- **Spot** provisioning (`--provisioning-model=SPOT`) — ~60-90% cheaper
  than on-demand. Fine for this: the job is a one-shot batch with no SLA
  (per `docs/adr/0001-*`'s "no SLA" framing), and if GCP preempts it
  mid-run you just re-run.
- `--maintenance-policy=TERMINATE` is required for any VM with an
  attached GPU (GPUs can't live-migrate).

### Two things that will break on a fresh VM (already handled by `bootstrap`)

1. **`pip install docling` breaks the preinstalled `torchaudio`.**
   `docling` pulls in `transformers`, which unconditionally imports
   `torchaudio` as part of its image-processing import chain. The DLVM
   image's preinstalled `torchaudio` build is ABI-incompatible with it
   (`undefined symbol: torch_library_impl`), so any docling conversion
   crashes at model-init time. Fix: `sudo python3 -m pip uninstall -y
   torchaudio` — docling/transformers only need it for optional audio
   features, table/layout inference doesn't touch it.
2. **TableFormer's `opencv-python` needs `libGL.so.1`.** The DLVM image
   is headless and doesn't ship it. Fix: `sudo apt-get install -y libgl1
   libglib2.0-0`.

If docling/transformers/opencv-python versions drift, these specific
errors may change shape — but "torchaudio import breaks docling" and
"opencv needs libGL" are the two failure modes to check for first.

### GPU quota

New/free-tier GCP projects often start with 0 GPU quota. Check before
provisioning:

```bash
gcloud compute regions describe us-central1 --project=$GCP_PROJECT \
  --format="value(quotas)" | tr ';' '\n' | grep -i t4
```

If `NVIDIA_T4_GPUS` limit is 0, request a quota increase (IAM & Admin >
Quotas in the console) before running `create`.

### Windows-specific notes

- `gcloud compute scp` on Windows shells out to PuTTY's `pscp`, which
  **does not support multiple remote source files in one call** — download
  one file per `scripts/gcp_gpu_spike.sh download` invocation, not a glob.
- If `gcloud` isn't on `PATH` in your shell, the Cloud SDK is typically at
  `%LOCALAPPDATA%\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.exe`.

### This was validated on a Qwiklabs training-lab project

The T4 spike run above used a temporary Qwiklabs student project
(`qwiklabs-gcp-*`), not a persistent project — those expire on a timer.
For Task 7's real batch run, use a real GCP project (`GCP_PROJECT=` your
own project id) with billing enabled and T4 quota confirmed.
