import pytest
import tempfile
import os
from unittest.mock import MagicMock
from core.crypto import CryptoManager
from core.database import DatabaseManager


@pytest.fixture
def temp_db():
    """Create a temporary SQLite database for testing"""
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    crypto = CryptoManager("testpassword")
    db = DatabaseManager(path, crypto)
    yield db
    db.close()
    os.unlink(path)


@pytest.fixture
def crypto():
    return CryptoManager("testpassword")


@pytest.fixture
def mock_ollama():
    """提供 mock 的 OllamaClient，用于隔离 AI 相关测试"""
    mock = MagicMock()
    mock.categorize.return_value = "开发工具"
    mock.generate.return_value = "这是一条 AI 生成的备注"
    mock.semantic_match.return_value = {
        "matched_ids": [1, 2],
        "reasoning": "测试推理",
        "confidence_scores": {"1": 0.9, "2": 0.8}
    }
    mock.generate_stream.return_value = iter(["你好", "世界"])
    return mock


@pytest.fixture
def temp_vault_file(tmp_path):
    """提供临时加密备份文件路径"""
    return tmp_path / "test_backup.vault"
