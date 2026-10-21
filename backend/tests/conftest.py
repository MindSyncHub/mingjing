import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.main import app  # noqa: E402


@pytest.fixture
def client():
    return TestClient(app)


# ---- 知识资产守卫（开源快照同步用） ----
# 以下测试依赖专有知识库文件；开源快照（MindSyncHub/mingjing）不含知识库，
# 文件缺失时自动 skip，保证 OSS 侧 CI 全绿。ranran 私有仓有知识库，不受影响。
from app.ui_api import KNOWLEDGE_GRAPH_HTML  # noqa: E402

_KNOWLEDGE_ASSET_TESTS = {
    "test_knowledge_graph_file_present",
}


def pytest_collection_modifyitems(items):
    if KNOWLEDGE_GRAPH_HTML.is_file():
        return
    for item in items:
        if item.name in _KNOWLEDGE_ASSET_TESTS:
            item.add_marker(
                pytest.mark.skip(reason="requires proprietary knowledge base (not included in the OSS release)")
            )
