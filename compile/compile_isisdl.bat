@echo off

rmdir /s /q __main__.build
rmdir /s /q __main__.dist
rmdir /s /q __main__.onefile-build

del isisdl-windows.exe

pip install ..
pip install nuitka zstandard imageio
py -m nuitka --standalone --onefile --lto=no --linux-onefile-icon=python_icon.png ../src/isisdl/__main__.py

ren __main__.exe isisdl-windows.exe
