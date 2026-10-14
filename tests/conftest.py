"""Test-suite safety net: block real outbound network during tests.

Every unit test here mocks `client._get` / `requests`, but nothing enforced it —
an orphaned repo-root script (`_tmp_failclosed_test`) once drove the real
credential resolver and hit live SAP XSUAA. This autouse guard makes that
impossible by default: any attempt to open a socket to a non-loopback address
during a test raises `LiveNetworkBlocked`, so a forgotten mock fails loudly as a
test error instead of silently calling a live tenant (and burning/leaking creds).

Loopback (127.0.0.1 / ::1) stays allowed so stdio subprocess and local-server
tests keep working. A test that genuinely needs outbound network can opt out with
the `allow_network` marker (none in this suite today).
"""

from __future__ import annotations

import socket

import pytest

_real_connect = socket.socket.connect
_LOOPBACK_PREFIXES = ("127.", "::1", "localhost")


class LiveNetworkBlocked(RuntimeError):
    """Raised when a test tries to open a real (non-loopback) network connection."""


def _is_loopback(address) -> bool:
    # address is (host, port) for AF_INET, (host, port, flow, scope) for AF_INET6,
    # or a str/bytes path for AF_UNIX. Allow unix sockets and loopback hosts.
    if isinstance(address, (str, bytes)):
        return True  # AF_UNIX / local pipe — not network egress
    try:
        host = address[0]
    except (TypeError, IndexError):
        return False
    host = str(host)
    return host == "::1" or host == "localhost" or host.startswith("127.")


@pytest.fixture(autouse=True)
def _block_live_network(request, monkeypatch):
    """Fail any test that opens a real outbound socket (unless it mocked the call)."""
    if request.node.get_closest_marker("allow_network"):
        yield
        return

    def guarded_connect(self, address):  # noqa: ANN001
        if not _is_loopback(address):
            raise LiveNetworkBlocked(
                f"Test attempted a live network connection to {address!r}. "
                "Mock the HTTP call (patch src.calm.client._get or requests), or "
                "mark the test with @pytest.mark.allow_network if it must hit the "
                "network."
            )
        return _real_connect(self, address)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    yield


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "allow_network: permit a test to open real outbound network connections.",
    )
