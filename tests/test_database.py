from unittest.mock import MagicMock, patch
from sqlalchemy import Column, Integer, String, Table
from app.models.base import Base, POSTGRES_NAMING_CONVENTION
from app.core.database import check_db_connectivity, get_db


def test_naming_convention_present():
    assert "ix" in POSTGRES_NAMING_CONVENTION
    assert "uq" in POSTGRES_NAMING_CONVENTION
    assert "ck" in POSTGRES_NAMING_CONVENTION
    assert "fk" in POSTGRES_NAMING_CONVENTION
    assert "pk" in POSTGRES_NAMING_CONVENTION
    assert Base.metadata.naming_convention == POSTGRES_NAMING_CONVENTION


def test_check_db_connectivity_failure():
    with patch("app.core.database.engine.connect", side_effect=Exception("Failed to connect")):
        connected, error = check_db_connectivity()
        assert connected is False
        assert "Failed to connect" in error


def test_check_db_connectivity_success():
    mock_conn = MagicMock()
    with patch("app.core.database.engine.connect", return_value=mock_conn):
        mock_conn.__enter__.return_value = mock_conn
        connected, error = check_db_connectivity()
        assert connected is True
        assert error is None


def test_alembic_upgrade_sqlite():
    from alembic.config import Config
    from alembic import command
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", "sqlite:///:memory:")
    command.upgrade(cfg, "head")

