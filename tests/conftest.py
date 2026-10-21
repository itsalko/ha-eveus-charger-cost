"""Test fixtures."""

import asyncio

import pytest

# aiodns starts a background thread the first time a resolver is created, which
# the Home Assistant test harness would report as a thread leaked by whichever
# test happened to create the first aiohttp session. Start it up front instead.
try:  # pragma: no cover
    import aiodns

    _loop = asyncio.new_event_loop()
    aiodns.DNSResolver(loop=_loop)
except Exception:  # pragma: no cover
    pass


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Allow loading this custom integration in tests."""
    yield
