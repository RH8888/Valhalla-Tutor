from unittest.mock import patch
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app


def test_liveness_endpoint():
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["app_name"] == settings.APP_NAME


def test_root_endpoint():
    with TestClient(app) as client:
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["app"] == settings.APP_NAME
        assert "health" in data


def test_readiness_healthy():
    with patch("app.routers.health.check_db_connectivity", return_value=(True, None)):
        with TestClient(app) as client:
            response = client.get("/health/db")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "healthy"
            assert data["database_connected"] is True
            assert data["timezone"] == "Asia/Tehran"
            assert data["database_error"] is None


def test_readiness_unhealthy():
    with patch("app.routers.health.check_db_connectivity", return_value=(False, "Connection refused (internal host 10.0.0.1)")):
        with patch("app.routers.health.logger.error") as mock_log:
            with TestClient(app) as client:
                response = client.get("/health/db")
                assert response.status_code == 503
                data = response.json()
                assert data["status"] == "unhealthy"
                assert data["database_connected"] is False
                # Ensure raw internal connection details are never leaked to client
                assert data["database_error"] == "Database connection unavailable"
                assert "10.0.0.1" not in str(data)
                # Verify raw details were logged server-side
                mock_log.assert_called_once()
                assert "10.0.0.1" in mock_log.call_args[0][1]
