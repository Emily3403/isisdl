#!/bin/bash

rm -rf venv/
rm -rf *.build
rm -rf *.dist

python3.8 -m venv venv
source venv/bin/activate
pip install -e ..
pip install nuitka zstandard

nuitka3 --standalone --onefile --linux-onefile-icon=python_icon.png ../src/isisdl/__main__.py &
nuitka3 --standalone --onefile --linux-onefile-icon=python_icon.png ../src/isisdl/bin/config.py &> /dev/null &
nuitka3 --standalone --onefile --linux-onefile-icon=python_icon.png ../src/isisdl/bin/sync_database.py &> /dev/null &
nuitka3 --standalone --onefile --linux-onefile-icon=python_icon.png ../src/isisdl/bin/compress.py &> /dev/null &

wait

mv ./__main__.bin ./isisdl-linux.bin
mv ./compress.bin ./isisdl-compress-linux.bin
mv ./config.bin ./isisdl-config-linux.bin
mv ./sync_database.bin ./isisdl-sync-linux.bin
