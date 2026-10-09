"""get_raw must resolve the site-relative attachment proxy path against BASE_URL."""

from unittest.mock import MagicMock

from parentsquare_mcp.client import PSClient
from parentsquare_mcp.config import BASE_URL


def _client():
    client = PSClient()
    client.session = MagicMock()
    client.session.get.return_value = MagicMock(status_code=200)
    return client


def test_get_raw_prepends_base_url_for_relative_path():
    client = _client()
    client.get_raw("/feeds/1/attachment/2")
    assert client.session.get.call_args.args[0] == f"{BASE_URL}/feeds/1/attachment/2"


def test_get_raw_leaves_absolute_urls_alone():
    client = _client()
    client.get_raw("https://psq.s3.amazonaws.com/flyer.pdf")
    assert client.session.get.call_args.args[0] == "https://psq.s3.amazonaws.com/flyer.pdf"
