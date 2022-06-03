#!/bin/bash

rm -rf __main__.*
rm -rf venv

python3.10 -m venv venv
source venv/bin/activate
pip install ..
pip install nuitka zstandard ordered-set

nuitka3 --standalone --onefile --linux-onefile-icon=python_icon.png ../src/isisdl/__main__.py

mv ./__main__.bin ./isisdl-linux.bin

echo "new sha256sum is"
sha256sum ./isisdl-linux.bin