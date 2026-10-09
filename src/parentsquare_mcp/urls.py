from __future__ import annotations

import re
from urllib.parse import parse_qs, urlsplit, urlunsplit

# bucket.s3.amazonaws.com, s3.us-west-2.amazonaws.com, s3-us-west-2.amazonaws.com
_S3_HOST_RE = re.compile(r"(?:.+\.)?s3(?:[.-][a-z0-9-]+)?\.amazonaws\.com")

_SIGNATURE_PARAMS = {"x-amz-signature", "signature"}

# ParentSquare's own download proxy, e.g. /feeds/91117195/attachment/291377755,
# which 302s to the pre-signed S3 object. Observed live 2026-10-08: post pages
# now link files through this path instead of linking S3 directly, so a
# host-only check reported "no attachments" on posts that clearly had a PDF.
_PROXY_PATH_RE = re.compile(r"/feeds/\d+/attachment/\d+")
_PROXY_HOSTS = {"", "www.parentsquare.com", "parentsquare.com"}


def is_attachment_href(href: str) -> bool:
    """True when *href* points at a ParentSquare file attachment.

    Matched on the parsed host rather than a substring of the whole URL: these
    hrefs come from school-authored HTML and are later fetched with the caller's
    authenticated session, so ``https://evil.example/?x=s3.amazonaws.com`` must
    not qualify.
    """
    try:
        parsed = urlsplit(href)
        host = (parsed.hostname or "").lower()
    except ValueError:
        return False

    if _S3_HOST_RE.fullmatch(host):
        return True

    # Site-relative (or same-host) proxy path. The fullmatch keeps traversal
    # and lookalike hosts out; an empty host means a relative href, which the
    # client resolves against BASE_URL.
    if host in _PROXY_HOSTS and _PROXY_PATH_RE.fullmatch(parsed.path):
        return True

    # Pre-signed downloads served through a CDN keep S3's query parameters.
    qs = {key.lower() for key in parse_qs(parsed.query)}
    return "response-content-disposition" in qs and bool(qs & _SIGNATURE_PARAMS)


def redact_url(url: str) -> str:
    """Strip the query string and any userinfo, which is where pre-signed URLs carry credentials."""
    try:
        parsed = urlsplit(url)
        host = parsed.hostname or ""
        port = parsed.port
    except ValueError:
        return "<unparseable url>"

    return urlunsplit((parsed.scheme, f"{host}:{port}" if port else host, parsed.path, "", ""))
