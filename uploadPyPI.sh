#!/bin/bash

mkdir -p dist/
rm dist/* 2> /dev/null
python3 -m build

# This uses the pypirc file: https://packaging.python.org/en/latest/specifications/pypirc/
twine upload dist/*
