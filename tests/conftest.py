"""全局测试隔离。

任何测试都不得读写真实的 %APPDATA%/PaperangP1（配置、任务库）——
真实服务可能正在运行并持有该 SQLite 的 WAL。conftest 把应用数据目录
强制指到每个用例独立的临时目录；job_queue 以值绑定了 config.APP_DIR，
需单独覆盖。
"""
import pytest

from paperang_p1 import config, job_queue


@pytest.fixture(autouse=True)
def isolate_app_data(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'APP_DIR', tmp_path)
    monkeypatch.setattr(config, 'CONFIG_PATH', tmp_path / 'config.json')
    monkeypatch.setattr(job_queue, 'APP_DIR', tmp_path)
