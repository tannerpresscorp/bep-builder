#!/bin/sh
# Installs numbers-parser (needed only for native .numbers files) in its own virtual
# environment, so its protobuf version can't clash with system packages. defusedxml is
# installed alongside openpyxl so returned Excel files are read safely.
# Prints the python to use: run read_tables.py / diff_tables.py with it for .numbers files.
VENV="${NUMBERS_VENV:-${TMPDIR:-/tmp}/numbers-venv}"
if [ ! -x "$VENV/bin/python" ]; then
  python3 -m venv "$VENV" || exit 1
fi
"$VENV/bin/pip" install -q numbers-parser openpyxl defusedxml >/dev/null 2>&1 || { echo "pip install failed" >&2; exit 1; }
"$VENV/bin/python" -c "import numbers_parser" || exit 1
echo "$VENV/bin/python"
