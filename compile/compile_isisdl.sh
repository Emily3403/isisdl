#!/bin/bash

rm -rf __main__.*
rm -rf venv

python3.11 -m venv venv
source venv/bin/activate
pip install ..


python3 -c "from isisdl.settings import is_static
assert(is_static)
" || exit 1


pip install  zstandard ordered-set
pip install nuitka

nuitka3 --standalone --onefile --linux-onefile-icon=python_icon.png ../src/isisdl/__main__.py

mv ./__main__.bin ./isisdl-linux.bin

echo "new sha256sum is"
sha256sum ./isisdl-linux.bin