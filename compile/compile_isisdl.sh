#!/bin/bash

rm -rf venv/
rm -rf *.build
rm -rf *.dist

python3.8 -m venv venv
source venv/bin/activate
pip install -e ..
pip install nuitka zstandard

nuitka3 --standalone --onefile --linux-onefile-icon=python_icon.png ../src/isisdl/__main__.py

mv ./__main__.bin ./isisdl-linux.bin
