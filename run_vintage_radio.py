"""
Entry point for PyInstaller and for running the app as a module.
Uses absolute imports so the frozen exe has a proper package context.
"""
from gui.radio_manager import run_app

if __name__ == "__main__":
    run_app()
