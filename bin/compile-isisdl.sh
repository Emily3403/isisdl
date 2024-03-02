#!/bin/bash

set -e
SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"

rm -rf "$SCRIPT_DIR"/static-compile/isisdl.*
rm -rf "$SCRIPT_DIR"/static-compile/venv

python3.11 -m venv "$SCRIPT_DIR"/static-compile/venv
source "$SCRIPT_DIR"/static-compile/venv/bin/activate
pip install "$SCRIPT_DIR"/..

python3 -c 'from isisdl.settings import is_static
assert is_static, "Error: For the static build, is_static must be True"
' || exit 1


pip install zstandard ordered-set nuitka
nuitka3 --standalone --onefile \
    --linux-onefile-icon="$SCRIPT_DIR"/static-compile/isisdl_icon.png \
    --output-dir="$SCRIPT_DIR"/static-compile \
    --output-filename=isisdl-linux.bin \
     "$SCRIPT_DIR"/../src/isisdl/__main__.py

echo "new sha256sum is"
sha256sum "$SCRIPT_DIR"/static-compile/isisdl-linux.bin
