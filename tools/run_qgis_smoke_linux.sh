#!/usr/bin/env bash
set -euo pipefail

workspace="${GITHUB_WORKSPACE:-$(pwd)}"
export FAKE_FARM_PLUGIN_PARENT="$workspace"
export QGIS_PREFIX_PATH="${QGIS_PREFIX_PATH:-/usr}"
export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-offscreen}"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/tmp/ffdg-runtime}"
mkdir -p "$XDG_RUNTIME_DIR"
chmod 700 "$XDG_RUNTIME_DIR"

python_paths=("$workspace")
for candidate in \
    /usr/share/qgis/python \
    /usr/share/qgis/python/plugins \
    /usr/local/share/qgis/python \
    /usr/local/share/qgis/python/plugins; do
  if [[ -d "$candidate" ]]; then
    python_paths+=("$candidate")
  fi
done
joined="$(IFS=:; echo "${python_paths[*]}")"
export PYTHONPATH="$joined${PYTHONPATH:+:$PYTHONPATH}"

python3 "$workspace/tests/qgis_smoke_test.py"
