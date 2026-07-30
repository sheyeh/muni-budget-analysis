#!/usr/bin/env bash
# scripts/gcp_gpu_spike.sh
#
# Provision a short-lived GCP GPU VM to run scripts/spike_docling.py (or any
# future docling batch run, e.g. prd.md Task 7) on CUDA instead of CPU.
#
# Why this exists: docling's layout + TableFormer models are torch-based.
# On CPU, ACCURATE-mode conversion of a 1-page vectored PDF took 78.7s;
# tel_aviv_2026.pdf (364pp) was infeasible on CPU (multi-hour extrapolation).
# On a spot NVIDIA T4, the same 364pp file converted in 1053s (~17.5 min).
# See docs/gcp-gpu-docling.md for the full writeup and known gotchas this
# script already works around (torchaudio ABI break, missing libGL.so.1).
#
# Usage:
#   export GCP_PROJECT=your-project-id   # required, no default on purpose
#   scripts/gcp_gpu_spike.sh create
#   scripts/gcp_gpu_spike.sh bootstrap
#   scripts/gcp_gpu_spike.sh upload scripts/spike_docling.py
#   scripts/gcp_gpu_spike.sh upload budget_examples/tel_aviv_2026.pdf
#   scripts/gcp_gpu_spike.sh run --only tel_aviv_2026 --device cuda
#   scripts/gcp_gpu_spike.sh download docs/examples/docling/tel_aviv_2026/native.json ./native.json
#   scripts/gcp_gpu_spike.sh delete      # do this when done -- it's billed by the hour
#
# Config (env vars, all but GCP_PROJECT have defaults):
#   GCP_PROJECT     (required)
#   GCP_ZONE         default: us-central1-a
#   INSTANCE_NAME    default: docling-gpu-spike
#   MACHINE_TYPE     default: n1-standard-4
#   GPU_TYPE         default: nvidia-tesla-t4
#   IMAGE_FAMILY     default: pytorch-2-9-cu129-ubuntu-2204-nvidia-580
#   IMAGE_PROJECT    default: ml-images
#   BOOT_DISK_SIZE   default: 100GB
#   REMOTE_DIR       default: ~/repo  -- files are uploaded/run under this
#                    path so scripts/spike_docling.py's REPO_ROOT resolution
#                    (parent.parent of the script) lines up, same as the
#                    real repo layout.

set -euo pipefail

: "${GCP_PROJECT:?Set GCP_PROJECT to your GCP project id}"
GCP_ZONE="${GCP_ZONE:-us-central1-a}"
INSTANCE_NAME="${INSTANCE_NAME:-docling-gpu-spike}"
MACHINE_TYPE="${MACHINE_TYPE:-n1-standard-4}"
GPU_TYPE="${GPU_TYPE:-nvidia-tesla-t4}"
IMAGE_FAMILY="${IMAGE_FAMILY:-pytorch-2-9-cu129-ubuntu-2204-nvidia-580}"
IMAGE_PROJECT="${IMAGE_PROJECT:-ml-images}"
BOOT_DISK_SIZE="${BOOT_DISK_SIZE:-100GB}"
REMOTE_DIR="${REMOTE_DIR:-repo}"

gcp() { gcloud "$@" --project="$GCP_PROJECT" --zone="$GCP_ZONE"; }

cmd_create() {
  gcp compute instances create "$INSTANCE_NAME" \
    --machine-type="$MACHINE_TYPE" \
    --image-family="$IMAGE_FAMILY" \
    --image-project="$IMAGE_PROJECT" \
    --accelerator="type=$GPU_TYPE,count=1" \
    --maintenance-policy=TERMINATE \
    --provisioning-model=SPOT \
    --instance-termination-action=STOP \
    --boot-disk-size="$BOOT_DISK_SIZE" \
    --boot-disk-type=pd-balanced
}

cmd_bootstrap() {
  # Installs docling + fixes two known breakages in the DLVM pytorch image:
  #   1. pip install docling pulls in transformers, which unconditionally
  #      imports torchaudio; the image's preinstalled torchaudio build is
  #      ABI-incompatible with it and segfaults on import. Fix: remove it --
  #      docling/transformers only need it for optional audio features.
  #   2. TableFormer's opencv-python dependency needs libGL.so.1, which this
  #      headless image doesn't ship.
  gcp compute ssh "$INSTANCE_NAME" --command='
    set -e
    pip install --quiet docling pypdf
    sudo python3 -m pip uninstall -y torchaudio
    sudo apt-get update -qq
    sudo apt-get install -y -qq libgl1 libglib2.0-0
    python3 -c "import docling, torch; print(\"docling\", docling.__version__, \"cuda available:\", torch.cuda.is_available())"
  '
}

cmd_upload() {
  local local_path="$1"
  # Preserve the path relative to repo root so REPO_ROOT resolution in
  # spike_docling.py (parent.parent of the script) matches the real layout.
  local rel_path
  rel_path="$(realpath --relative-to="$(git rev-parse --show-toplevel)" "$local_path")"
  gcp compute ssh "$INSTANCE_NAME" --command="mkdir -p ~/$REMOTE_DIR/$(dirname "$rel_path")"
  gcp compute scp "$local_path" "$INSTANCE_NAME:~/$REMOTE_DIR/$rel_path"
}

cmd_run() {
  # Runs in the foreground and streams output -- for a 364pp ACCURATE-mode
  # run expect ~15-20 minutes. Ctrl-C locally does NOT stop the remote job;
  # SSH back in and re-run with the same command to check on it, or use
  # `nohup ... &` inside --command if you want it detached.
  gcp compute ssh "$INSTANCE_NAME" --command="cd ~/$REMOTE_DIR && python3 scripts/spike_docling.py $*"
}

cmd_download() {
  local remote_path="$1" local_path="$2"
  gcp compute scp "$INSTANCE_NAME:~/$REMOTE_DIR/$remote_path" "$local_path"
}

cmd_delete() {
  gcp compute instances delete "$INSTANCE_NAME" --quiet
}

case "${1:-}" in
  create)   cmd_create ;;
  bootstrap) cmd_bootstrap ;;
  upload)   shift; cmd_upload "$@" ;;
  run)      shift; cmd_run "$@" ;;
  download) shift; cmd_download "$@" ;;
  delete)   cmd_delete ;;
  *)
    echo "Usage: $0 {create|bootstrap|upload <path>|run <spike_docling.py args...>|download <remote> <local>|delete}" >&2
    exit 1
    ;;
esac
