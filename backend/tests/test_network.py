from unittest.mock import patch

import pytest

from services.network import validate_upstream_url


def test_upstream_rejects_private_and_loopback_addresses():
    for ip in ("127.0.0.1", "10.0.0.8", "169.254.169.254", "::1"):
        with patch("services.network.socket.getaddrinfo", return_value=[(2, 1, 6, "", (ip, 443))]):
            with pytest.raises(ValueError):
                validate_upstream_url("https://upstream.example/v1")


def test_upstream_accepts_public_https_without_credentials():
    with patch("services.network.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 443))]):
        assert validate_upstream_url("https://upstream.example/v1/") == "https://upstream.example/v1"


@pytest.mark.parametrize("url", ["file:///etc/passwd", "https://user:pass@example.com/v1", "https://example.com/v1?x=1"])
def test_upstream_rejects_invalid_url_shapes(url):
    with patch("services.network.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 443))]):
        with pytest.raises(ValueError):
            validate_upstream_url(url)
