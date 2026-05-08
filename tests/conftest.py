import pytest
import tempfile
import os
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
