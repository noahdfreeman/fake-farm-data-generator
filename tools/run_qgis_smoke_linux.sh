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

smoke_log="$(mktemp)"
trap 'rm -f "$smoke_log"' EXIT

# Some official QGIS 3.x container images exit with SIGSEGV while tearing down
# Qt/PyQt after the smoke test has fully completed. Preserve genuine failures,
# but accept that known shutdown-only condition when the test emitted its final
# success marker.
set +e
python3 "$workspace/tests/qgis_smoke_test.py" 2>&1 | tee "$smoke_log"
smoke_status=${PIPESTATUS[0]}
set -e

if [[ $smoke_status -eq 0 ]]; then
  exit 0
fi

if grep -q '^QGIS_SMOKE_OK ' "$smoke_log"; then
  echo "QGIS smoke assertions passed; ignoring native shutdown exit $smoke_status." >&2
  exit 0
fi

exit "$smoke_status"
