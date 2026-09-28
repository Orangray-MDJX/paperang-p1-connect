"""Start the native management window from this checkout."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from paperang_p1.native_window import run

run()
