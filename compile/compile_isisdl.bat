del /q venv
del /q *.build
del /q *.dist

pip install -e ..
pip install nuitka zstandard

nuitka3 --standalone --onefile --linux-onefile-icon=python_icon.png ../src/isisdl/__main__.py
