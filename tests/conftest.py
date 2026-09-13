import os
import sys
import matplotlib

# Set matplotlib backend to Agg to avoid GUI issues
matplotlib.use('Agg')

# Add project root to python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


# The composed product authenticates real routes. Tests provision an explicitly
# synthetic local installation; guards are never disabled for positive paths.
import base64
from datetime import date, timedelta
import json
from pathlib import Path
from urllib.parse import urlsplit

import pytest


def pytest_configure(config):
    config.addinivalue_line("markers", "raw_local_auth: exercise missing/invalid credentials without automatic test headers")


@pytest.fixture(scope="session", autouse=True)
def synthetic_local_installation(tmp_path_factory):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    from modules.commercial_license import make_signed_envelope
    patch = pytest.MonkeyPatch()
    patch.setenv("MODELA_TEST_CONTEXT", "1")
    root = tmp_path_factory.mktemp("SYNTHETIC_TEST_installation")
    patch.setenv("LOCAL_AUTH_TOKEN", os.environ.get("LOCAL_AUTH_TOKEN") or "SYNTHETIC_TEST_local_bearer_0123456789")
    patch.setenv("LOCAL_CSRF_SECRET", os.environ.get("LOCAL_CSRF_SECRET") or base64.urlsafe_b64encode(
        b"SYNTHETIC_TEST_CSRF_secret_0123456789").decode())
    if not os.environ.get("MODELA_LICENSE_PATH"):
        key = Ed25519PrivateKey.generate()
        path = root / "SYNTHETIC_TEST_entitlement.json"
        path.write_text(json.dumps(make_signed_envelope({
            "license_id": "SYNTHETIC_TEST_ONLY", "expires_on": (date.today() + timedelta(days=2)).isoformat(),
            "rights": ["calculate", "read", "export"],
        }, key)))
        patch.setenv("MODELA_LICENSE_PATH", str(path))
        patch.setenv("MODELA_LICENSE_PUBLIC_KEY", base64.urlsafe_b64encode(
            key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode())
    yield
    patch.undo()


@pytest.fixture(autouse=True)
def authenticated_local_test_clients(request, monkeypatch, synthetic_local_installation):
    """Supply valid credentials to local test clients; explicit negatives opt out."""
    if request.node.get_closest_marker("raw_local_auth"):
        return
    import httpx
    import requests
    from fastapi.testclient import TestClient
    from modules.operacao_local.runtime import local_client_headers

    def headers_for(url, supplied):
        hostname = urlsplit(str(url)).hostname
        if hostname is None or hostname in {"127.0.0.1", "localhost", "::1", "testserver"}:
            defaults = {k.lower(): v for k, v in local_client_headers().items()}
            defaults.update({k.lower(): v for k, v in (supplied or {}).items()})
            return defaults
        return supplied

    http_request = httpx.Client.request
    def authenticated_http(self, method, url, **kwargs):
        kwargs["headers"] = headers_for(url, kwargs.get("headers"))
        return http_request(self, method, url, **kwargs)
    monkeypatch.setattr(httpx.Client, "request", authenticated_http)
    requests_request = requests.Session.request
    def authenticated_requests(self, method, url, **kwargs):
        kwargs["headers"] = headers_for(url, kwargs.get("headers"))
        return requests_request(self, method, url, **kwargs)
    monkeypatch.setattr(requests.Session, "request", authenticated_requests)
    websocket_connect = TestClient.websocket_connect
    def authenticated_websocket(self, url, **kwargs):
        kwargs["headers"] = headers_for(url, kwargs.get("headers"))
        return websocket_connect(self, url, **kwargs)
    monkeypatch.setattr(TestClient, "websocket_connect", authenticated_websocket)
