@echo off

pip install ..
pip install nuitka zstandard imageio

py -m nuitka --standalone --onefile --lto=no --linux-onefile-icon=python_icon.png ../src/isisdl/__main__.py

del isisdl-windows.exe
ren __main__.exe isisdl-windows.exe
