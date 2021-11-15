#!/bin/bash

mkdir -p dist/
rm dist/* 2> /dev/null
python3 -m build

twine upload dist/*
