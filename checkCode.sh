#!/bin/bash

SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"

source "$SCRIPT_DIR/venv/bin/activate"

dmypy run src tests
flake8 src tests
