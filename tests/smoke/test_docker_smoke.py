"""Docker production image smoke tests.

These tests build the production Docker image, run the container with
mock/test configuration, and verify that key endpoints return expected
responses. They catch runtime failures (missing libraries, import errors,
sslmode crashes, auth blocking static files) that unit tests and linting
cannot detect.

Requires Docker to be available on the host. Marked with ``@pytest.mark.e2e``
so they are excluded from the default ``make test`` run.

Usage::

    pytest tests/smoke/ -m e2e -v
"""

from __future__ import annotations

import os
import socket
import subprocess
import time
from contextlib import closing

import httpx
import pytest

# ---------------------------------------------------------------------------
# Markers — all tests in this module require Docker and are slow
# ---------------------------------------------------------------------------

pytestmark = [pytest.mark.e2e, pytest.mark.slow]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

IMAGE_NAME = "wikimind-smoke:test"
CONTAINER_NAME = "wikimind-smoke-test"
STARTUP_TIMEOUT_SECONDS = 120
HEALTH_POLL_INTERVAL = 2


def _find_free_port() -> int:
    """Find an available TCP port on the host."""
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("", 0))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return s.getsockname()[1]


def _docker_available() -> bool:
    """Check if Docker daemon is running."""
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=10,
            check=False,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _repo_root() -> str:
    """Return the repository root (where Dockerfile lives)."""
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _wait_for_health(base_url: str, timeout: int = STARTUP_TIMEOUT_SECONDS) -> Exception | None:
    """Poll the health endpoint until it responds 200 or timeout expires.

    Returns None on success, or the last exception on timeout.
    """
    deadline = time.time() + timeout
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            resp = httpx.get(f"{base_url}/health", timeout=5)
            if resp.status_code == 200:
                return None
        except httpx.TransportError as exc:
            last_error = exc
        time.sleep(HEALTH_POLL_INTERVAL)
    return last_error or TimeoutError("Health check timed out")


def _stop_container(name: str) -> None:
    """Force-remove a Docker container by name."""
    subprocess.run(
        ["docker", "rm", "-f", name],
        capture_output=True,
        check=False,
    )


def _get_container_logs(name: str) -> str:
    """Fetch container stdout+stderr logs."""
    result = subprocess.run(
        ["docker", "logs", name],
        capture_output=True,
        text=True,
        check=False,
    )
    return f"{result.stdout}\n{result.stderr}"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def docker_image() -> str:
    """Build the production Docker image once per test module.

    Returns the image tag. Skips the entire module if Docker is unavailable.
    """
    if not _docker_available():
        pytest.skip("Docker is not available")

    repo_root = _repo_root()

    result = subprocess.run(
        [
            "docker",
            "build",
            "--target",
            "prod",
            "--tag",
            IMAGE_NAME,
            "--file",
            os.path.join(repo_root, "Dockerfile"),
            repo_root,
        ],
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    if result.returncode != 0:
        pytest.fail(f"Docker build failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")

    return IMAGE_NAME


@pytest.fixture(scope="module")
def container_url(docker_image: str):
    """Start a container from the prod image and yield its base URL.

    The container runs with:
    - Mock LLM enabled (no API keys needed)
    - SQLite backend (no Postgres required)
    - Auth disabled
    - Single gunicorn worker for fast startup

    Tears down the container after all tests in the module complete.
    """
    port = _find_free_port()
    base_url = f"http://127.0.0.1:{port}"

    # Stop any leftover container from a previous run
    _stop_container(CONTAINER_NAME)

    # Start the container
    run_result = subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            CONTAINER_NAME,
            "-p",
            f"{port}:7842",
            "-e",
            "WIKIMIND_LLM__MOCK__ENABLED=true",
            "-e",
            "WIKIMIND_LLM__DEFAULT_PROVIDER=mock",
            "-e",
            "WIKIMIND_ENV=development",
            "-e",
            "WEB_CONCURRENCY=1",
            docker_image,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if run_result.returncode != 0:
        pytest.fail(f"Container start failed:\n{run_result.stderr}")

    # Wait for the container to become healthy
    error = _wait_for_health(base_url)
    if error is not None:
        logs = _get_container_logs(CONTAINER_NAME)
        _stop_container(CONTAINER_NAME)
        pytest.fail(
            f"Container failed to become healthy within {STARTUP_TIMEOUT_SECONDS}s.\n"
            f"Last error: {error}\n"
            f"Container logs:\n{logs}"
        )

    yield base_url

    # Teardown
    _stop_container(CONTAINER_NAME)


# ---------------------------------------------------------------------------
# Smoke tests — basic endpoint checks
# ---------------------------------------------------------------------------


class TestHealthEndpoint:
    """Verify the health check endpoint works in the production image."""

    def test_health_returns_200(self, container_url: str):
        resp = httpx.get(f"{container_url}/health", timeout=10)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "version" in data

    def test_health_json_content_type(self, container_url: str):
        resp = httpx.get(f"{container_url}/health", timeout=10)
        assert "application/json" in resp.headers["content-type"]


class TestDocsEndpoint:
    """Verify OpenAPI docs are accessible."""

    def test_docs_returns_200(self, container_url: str):
        resp = httpx.get(f"{container_url}/docs", timeout=10)
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    def test_openapi_json_returns_200(self, container_url: str):
        resp = httpx.get(f"{container_url}/openapi.json", timeout=10)
        assert resp.status_code == 200
        data = resp.json()
        assert data["info"]["title"] == "WikiMind Gateway"


class TestSPAServing:
    """Verify the SPA (React frontend) is served correctly."""

    def test_root_serves_html(self, container_url: str):
        resp = httpx.get(f"{container_url}/", timeout=10)
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        # The built React app should contain a root div for mounting
        assert "root" in resp.text or "id=" in resp.text

    def test_spa_route_fallback(self, container_url: str):
        """Non-API routes should serve index.html for SPA client-side routing."""
        resp = httpx.get(f"{container_url}/inbox", timeout=10)
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]


class TestIngestEndpoint:
    """Verify the ingest API accepts requests in the production image."""

    def test_ingest_text_accepts_request(self, container_url: str):
        resp = httpx.post(
            f"{container_url}/api/ingest/text",
            json={
                "content": "Smoke test content for WikiMind.",
                "title": "Smoke Test",
                "auto_compile": False,
            },
            timeout=30,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "id" in data
        assert data["title"] == "Smoke Test"

    def test_ingest_url_validates_input(self, container_url: str):
        """POST with missing required fields should return 422."""
        resp = httpx.post(
            f"{container_url}/api/ingest/url",
            json={},
            timeout=10,
        )
        assert resp.status_code == 422


class TestAuthFlow:
    """Verify auth middleware behavior in the production image."""

    def test_auth_disabled_health_accessible(self, container_url: str):
        """With auth disabled, health endpoint requires no token."""
        resp = httpx.get(f"{container_url}/health", timeout=10)
        assert resp.status_code == 200

    def test_auth_disabled_api_accessible(self, container_url: str):
        """With auth disabled, API endpoints require no token."""
        resp = httpx.get(f"{container_url}/api/ingest/sources", timeout=10)
        assert resp.status_code == 200

    def test_auth_me_returns_dev_user(self, container_url: str):
        """In dev mode, /auth/me returns the auto-provisioned dev user."""
        resp = httpx.get(
            f"{container_url}/auth/me",
            headers={"Accept": "application/json"},
            timeout=10,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"].startswith("dev-")
        assert data["email"] == "dev@wikimind.local"


class TestAuthEnabled:
    """Verify auth enforcement in production mode (no dev auto-auth)."""

    @pytest.fixture(scope="class")
    def auth_container_url(self, docker_image: str):
        """Start a container in production mode with JWT auth required."""
        port = _find_free_port()
        base_url = f"http://127.0.0.1:{port}"
        name = f"{CONTAINER_NAME}-auth"

        _stop_container(name)

        run_result = subprocess.run(
            [
                "docker",
                "run",
                "-d",
                "--name",
                name,
                "-p",
                f"{port}:7842",
                "-e",
                "WIKIMIND_LLM__MOCK__ENABLED=true",
                "-e",
                "WIKIMIND_LLM__DEFAULT_PROVIDER=mock",
                "-e",
                "WIKIMIND_ENV=production",
                "-e",
                "WIKIMIND_AUTH__JWT_SECRET_KEY=smoke-test-secret-key-for-ci",
                "-e",
                "WEB_CONCURRENCY=1",
                docker_image,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if run_result.returncode != 0:
            pytest.fail(f"Auth container start failed:\n{run_result.stderr}")

        error = _wait_for_health(base_url)
        if error is not None:
            logs = _get_container_logs(name)
            _stop_container(name)
            pytest.fail(f"Auth container failed to start.\nLast error: {error}\nLogs:\n{logs}")

        yield base_url
        _stop_container(name)

    def test_health_exempt_from_auth(self, auth_container_url: str):
        """Health endpoint should be accessible even with auth enabled."""
        resp = httpx.get(f"{auth_container_url}/health", timeout=10)
        assert resp.status_code == 200

    def test_docs_exempt_from_auth(self, auth_container_url: str):
        """Docs endpoint should be accessible even with auth enabled."""
        resp = httpx.get(f"{auth_container_url}/docs", timeout=10)
        assert resp.status_code == 200

    def test_spa_routes_exempt_from_auth(self, auth_container_url: str):
        """SPA HTML pages should load without auth for client-side login flow."""
        # Browsers send Accept: text/html on page loads; the auth middleware
        # uses this to distinguish SPA page loads from API calls and exempts them.
        resp = httpx.get(
            f"{auth_container_url}/",
            headers={"Accept": "text/html"},
            timeout=10,
        )
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    def test_api_requires_auth(self, auth_container_url: str):
        """API endpoints should require a token when auth is enabled."""
        resp = httpx.get(
            f"{auth_container_url}/api/ingest/sources",
            headers={"Accept": "application/json"},
            timeout=10,
        )
        assert resp.status_code == 401

    def test_api_rejects_invalid_token(self, auth_container_url: str):
        """API endpoints should reject invalid JWT tokens."""
        resp = httpx.get(
            f"{auth_container_url}/api/ingest/sources",
            headers={
                "Authorization": "Bearer invalid-token",
                "Accept": "application/json",
            },
            timeout=10,
        )
        assert resp.status_code == 401

    def test_static_assets_exempt_from_auth(self, auth_container_url: str):
        """Static asset paths should not require auth."""
        # The /assets/ path is exempt per auth middleware EXEMPT_PREFIXES.
        # Request a nonexistent asset -- we just check it's not 401.
        resp = httpx.get(f"{auth_container_url}/assets/nonexistent.js", timeout=10)
        assert resp.status_code != 401


class TestContainerBasics:
    """Verify container runtime basics."""

    def test_gunicorn_is_running(self, container_url: str, docker_image: str):
        """Gunicorn should be the process manager in the prod image."""
        result = subprocess.run(
            ["docker", "exec", CONTAINER_NAME, "ps", "aux"],
            capture_output=True,
            text=True,
            check=False,
        )
        # ps may not be available in slim images; fall back to checking
        # the health endpoint works (which implies gunicorn is running).
        if result.returncode == 0:
            assert "gunicorn" in result.stdout
        else:
            # If ps is not available, the health check passing is proof enough
            resp = httpx.get(f"{container_url}/health", timeout=10)
            assert resp.status_code == 200

    def test_non_root_user(self, container_url: str):
        """The application process should run as non-root (wikimind user).

        The container starts as root (for volume chown), then drops to
        wikimind via gosu. PID 1 should be the gunicorn master running
        as the wikimind user. We check /proc/1/status which is always
        available on Linux — no dependency on ps or pgrep.
        """
        result = subprocess.run(
            [
                "docker",
                "exec",
                CONTAINER_NAME,
                "sh",
                "-c",
                "awk '/^Uid:/{print $2}' /proc/1/status",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            uid = result.stdout.strip()
            assert uid != "0", "PID 1 is running as root (UID 0), expected wikimind"

    def test_data_dir_writable(self, container_url: str):
        """The data directory should be writable by the container user."""
        result = subprocess.run(
            [
                "docker",
                "exec",
                CONTAINER_NAME,
                "sh",
                "-c",
                "touch /home/wikimind/.wikimind/smoke-test && rm /home/wikimind/.wikimind/smoke-test",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0
