#!/bin/bash

set -e
SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"

cd "$SCRIPT_DIR"/.. || exit 1

mkdir -p "$SCRIPT_DIR"/dist/
rm "$SCRIPT_DIR"/dist/* 2> /dev/null
python3 -m build --outdir "$SCRIPT_DIR/dist/"

twine upload "$SCRIPT_DIR"/dist/*
