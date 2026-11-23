@echo off
rem Opens the search window. Settings: search.toml. Results: runs folder.
cd /d "%~dp0"
start "" pythonw ui.py
