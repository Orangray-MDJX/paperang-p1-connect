# PyInstaller entry: run the paperang_p1 service as a standalone exe.
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import asyncio

from paperang_p1.service import main

if __name__ == "__main__":
    asyncio.run(main())
