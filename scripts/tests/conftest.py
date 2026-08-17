"""pytest 配置：保证可以从 scripts/tests/ 导入 scripts 下的模块。"""
import os
import sys

import pytest


def pytest_configure(config):
    config.addinivalue_line("markers", "e2e: real-network BaoStock end-to-end tests")


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 指向 repo 根目录（scripts/ 的上一级）
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCHEMA = os.path.join(ROOT, "backend", "database", "schema.sql")
