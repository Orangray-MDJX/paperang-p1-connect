"""Absolute-path tray launcher for HKCU Run."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from paperang_p1.tray import run
run()
