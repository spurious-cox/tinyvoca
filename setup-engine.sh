#!/bin/zsh
# Builds TinyVoca's speech engine: a Python virtual environment with PyTorch and tiny-voca, and the model weights.
# TinyVoca.app runs this on first launch; you can also run it yourself:  ./setup-engine.sh [folder]
# Exit codes: 0 ready, 3 no suitable Python (3.10 or newer) found, anything else a failed step.
set -e
ROOT="${1:-$HOME/Library/Application Support/TinyVoca}"

# The exact upstream commits this version of TinyVoca was tested with.
TINY_VOCA_SHA="62e2adef158bc997042cc6234f541f1e0e4cd55d"   # https://github.com/n4ze3m/tiny-voca
DIZIONE_SHA="8cd889e4de7be6bd1dd2e6891344a0729fa14dd4"      # https://github.com/n4ze3m/dizione (phonemizer)
WEIGHTS_REPO="n4ze3m/tiny-voca"                              # https://huggingface.co/n4ze3m/tiny-voca

mkdir -p "$ROOT"
cd "$ROOT"
rm -f .ready

pick_python() {
    local c
    for c in /opt/homebrew/bin/python3.13 /opt/homebrew/bin/python3.12 /opt/homebrew/bin/python3.11 /opt/homebrew/bin/python3.10 \
             /opt/homebrew/bin/python3 /usr/local/bin/python3.13 /usr/local/bin/python3.12 /usr/local/bin/python3.11 \
             /usr/local/bin/python3.10 /usr/local/bin/python3 /Library/Frameworks/Python.framework/Versions/Current/bin/python3 \
             $(xcode-select -p >/dev/null 2>&1 && print /usr/bin/python3); do
        [[ -x "$c" ]] || continue
        if "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
            print -r -- "$c"; return 0
        fi
    done
    return 1
}

print "Step 1 of 4: looking for Python 3.10 or newer"
PY=$(pick_python) || { print "No Python 3.10 or newer was found."; exit 3; }
print "  using $PY ($($PY --version 2>&1))"

print "Step 2 of 4: creating the Python environment"
if [[ ! -x venv/bin/python ]] || ! venv/bin/python -c 'import sys' 2>/dev/null; then
    rm -rf venv
    "$PY" -m venv venv
fi

print "Step 3 of 4: installing PyTorch and tiny-voca (about 250 MB; this is the slow step)"
venv/bin/python -m pip install --disable-pip-version-check --progress-bar off \
    "https://github.com/n4ze3m/dizione/archive/$DIZIONE_SHA.zip" \
    "https://github.com/n4ze3m/tiny-voca/archive/$TINY_VOCA_SHA.zip" \
    huggingface_hub

print "Step 4 of 4: downloading the model weights (about 25 MB)"
HF_HUB_DISABLE_TELEMETRY=1 venv/bin/python - <<PYEOF
from huggingface_hub import snapshot_download
snapshot_download("$WEIGHTS_REPO", local_dir="weights",
                  allow_patterns=["tiny-voca.pt", "config.json", "LICENSE", "phonemizer/*"])
PYEOF

[[ -f weights/tiny-voca.pt && -f weights/phonemizer/lexicon.json ]] || { print "The weights did not download completely."; exit 4; }
venv/bin/python -c 'import torch, tiny_voca, dizione' || { print "The installed packages do not load."; exit 5; }

print "1" > .ready
print "Ready."
