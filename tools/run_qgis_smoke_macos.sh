#!/usr/bin/env bash
set -euo pipefail

workspace="${GITHUB_WORKSPACE:-$(pwd)}"
qgis_app="${QGIS_APP_PATH:-}"

if [[ -z "$qgis_app" ]]; then
  for candidate in /Applications/QGIS.app /Applications/QGIS-LTR.app; do
    if [[ -d "$candidate" ]]; then
      qgis_app="$candidate"
      break
    fi
  done
fi

if [[ -z "$qgis_app" ]]; then
  qgis_app="$(find /Applications -maxdepth 1 -type d -name 'QGIS*.app' -print -quit)"
fi

if [[ -z "$qgis_app" || ! -d "$qgis_app/Contents" ]]; then
  echo "Could not locate an installed QGIS application bundle." >&2
  exit 2
fi

contents="$qgis_app/Contents"
macos="$contents/MacOS"
resources="$contents/Resources"

if [[ ! -d "$macos" || ! -d "$resources" ]]; then
  echo "QGIS bundle is missing Contents/MacOS or Contents/Resources: $qgis_app" >&2
  exit 2
fi

shopt -s nullglob
python_candidates=(
  "$macos/python3"
  "$macos/python"
  "$macos"/python3.*
  "$macos/bin/python3"
  "$macos/bin/python"
  "$macos"/bin/python3.*
  "$contents/Frameworks/Python.framework/Versions/Current/bin/python3"
  "$contents/Frameworks/Python.framework/Versions/Current/bin/python"
  "$contents"/Frameworks/Python.framework/Versions/*/bin/python3
  "$contents"/Frameworks/Python.framework/Versions/*/bin/python
  "$contents"/Frameworks/Python.framework/Versions/*/Resources/Python.app/Contents/MacOS/Python
)
shopt -u nullglob

qgis_python=""
for candidate in "${python_candidates[@]}"; do
  if [[ -x "$candidate" && "$candidate" != *-config ]]; then
    qgis_python="$candidate"
    break
  fi
done

if [[ -z "$qgis_python" ]]; then
  echo "Could not locate QGIS's embedded Python executable under $contents." >&2
  find "$contents" -maxdepth 5 -type f -name 'python3*' -print >&2 || true
  exit 2
fi

export FAKE_FARM_PLUGIN_PARENT="$workspace"
export QGIS_PREFIX_PATH="$macos"
export PYTHONNOUSERSITE=1
export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-offscreen}"
export PATH="$macos/bin:$PATH"

if [[ "$qgis_python" == "$macos"/* ]]; then
  export PYTHONHOME="${PYTHONHOME:-$macos}"
else
  unset PYTHONHOME
fi

python_paths=("$workspace")
for candidate in \
    "$resources/python" \
    "$resources/python/plugins" \
    "$macos/share/qgis/python" \
    "$macos/share/qgis/python/plugins"; do
  if [[ -d "$candidate" ]]; then
    python_paths+=("$candidate")
  fi
done

# QGIS 4 macOS packages may place the Processing provider outside the older
# Resources/python/plugins and MacOS/share/qgis/python/plugins locations.
# Discover the provider by its stable module entry point and add its parent.
while IFS= read -r plugin_parent; do
  if [[ ! " ${python_paths[*]} " =~ " $plugin_parent " ]]; then
    python_paths+=("$plugin_parent")
  fi
done < <(find "$contents" -type f -path '*/processing/core/Processing.py' -print 2>/dev/null | sed 's|/processing/core/Processing.py$||')
joined_python_path="$(IFS=:; echo "${python_paths[*]}")"
export PYTHONPATH="$joined_python_path${PYTHONPATH:+:$PYTHONPATH}"

if [[ -d "$macos/lib" ]]; then
  export DYLD_LIBRARY_PATH="$macos/lib${DYLD_LIBRARY_PATH:+:$DYLD_LIBRARY_PATH}"
fi

for candidate in "$resources/qgis/gdal" "$resources/gdal"; do
  if [[ -d "$candidate" ]]; then
    export GDAL_DATA="$candidate"
    break
  fi
done

for candidate in "$resources/qgis/proj" "$resources/proj"; do
  if [[ -d "$candidate" ]]; then
    export PROJ_LIB="$candidate"
    break
  fi
done

if [[ -d "$macos/lib/gdalplugins" ]]; then
  export GDAL_DRIVER_PATH="$macos/lib/gdalplugins"
fi

if [[ -f "$resources/certs/certs.pem" ]]; then
  export SSL_CERT_FILE="$resources/certs/certs.pem"
  export SSL_CERT_DIR="$resources/certs"
fi

echo "QGIS application: $qgis_app"
echo "QGIS Python: $qgis_python"
echo "QGIS Python path: $PYTHONPATH"
"$qgis_python" --version
"$qgis_python" "$workspace/tests/qgis_smoke_test.py"
