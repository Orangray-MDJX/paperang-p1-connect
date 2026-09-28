"""Absolute-path launcher for HKCU Run (no installed package required)."""
import asyncio
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from paperang_p1.service import main, setup_logging
setup_logging()
try:
    asyncio.run(main())
except Exception:
    import logging
    logging.getLogger(__name__).exception('后台打印服务启动或运行失败')
    raise SystemExit(1)
