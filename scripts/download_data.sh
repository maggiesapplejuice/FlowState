#!/usr/bin/env bash
# Download the project's one dataset: HAI (HIL-based Augmented ICS) from its authors' GitHub repository.
# The water process in HAI is run by a Siemens S7-300 PLC.
#   HAI 22.04: the core (6 normal training files, 4 test files with 58 attacks, 10 on the water process)
#   HAI 23.05: same testbed setup as 22.04 (4 normal training files, 2 test files, 1 water-process attack)
# Also fetches HAI's technical document and, if missing, the local language model for incident briefs.
# Usage: bash scripts/download_data.sh   (files that already exist are skipped)
set -uo pipefail
cd "$(dirname "$0")/.."
MEDIA=https://media.githubusercontent.com/media/icsdataset/hai/master
RAW=https://raw.githubusercontent.com/icsdataset/hai/master
FAILED=()
get() {  # get <url> <output path>
  local url="$1" out="$2"
  if [ -s "$out" ]; then echo "  have  $out"; return 0; fi
  mkdir -p "$(dirname "$out")"
  if curl -sSfL --retry 3 -o "$out.part" "$url" && [ "$(head -c 5 "$out.part")" != "versi" ]; then
    mv "$out.part" "$out"; echo "  got   $out ($(du -h "$out" | cut -f1))"
  else
    rm -f "$out.part"; echo "  FAIL  $out"; FAILED+=("$out")
  fi
}
echo "== HAI 22.04"
for f in train1 train2 train3 train4 train5 train6 test1 test2 test3 test4; do
  get "$MEDIA/hai-22.04/$f.csv" "data/raw/hai-22.04/$f.csv"
done
echo "== HAI 23.05"
for f in hai-train1 hai-train2 hai-train3 hai-train4 hai-test1 hai-test2 label-test1 label-test2; do
  get "$MEDIA/hai-23.05/$f.csv" "data/raw/hai-23.05/$f.csv"
done
echo "== HAI technical document"
get "$RAW/hai_dataset_technical_details.pdf" "data/raw/hai_dataset_technical_details.pdf"
echo "== Language model for incident briefs (IBM Granite 3.3 2B Instruct, big-endian build for IBM Z)"
get "https://huggingface.co/taronaeo/Granite-3.3-2B-Instruct-BE-GGUF/resolve/main/granite-3.3-2b-instruct-be.Q4_K_M.gguf" "models/granite-3.3-2b-instruct-be.Q4_K_M.gguf"
echo
echo "Disk used: data/ $(du -sh data | cut -f1), models/ $(du -sh models | cut -f1)"
if [ ${#FAILED[@]} -gt 0 ]; then echo "Failed (re-run to retry):"; printf '  %s\n' "${FAILED[@]}"; exit 1; fi
echo "All downloads complete."
