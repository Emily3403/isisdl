del /q venv
del /q *.build
del /q *.dist

pip install ..
pip install nuitka zstandard

py -m nuitka --standalone --onefile --no-lto --linux-onefile-icon=python_icon.png ../src/isisdl/__main__.py
