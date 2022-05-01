del /q venv
del /q *.build
del /q *.dist

pip install ..
pip install nuitka zstandard imageio

py -m nuitka --standalone --onefile --lto=no --linux-onefile-icon=python_icon.png ../src/isisdl/__main__.py

ren __main__.exe isisdl-windows.exe
