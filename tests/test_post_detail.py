"""Synthetic post-detail fixtures; no production content."""

from bs4 import BeautifulSoup

from parentsquare_mcp.parsers.feeds import parse_post_detail


def _page(body: str) -> BeautifulSoup:
    return BeautifulSoup(
        '<div class="feed-show"><div class="feed-title"><div class="subject">'
        '<span role="heading">Agenda</span></div></div>'
        '<div class="feed-metadata"><a class="user-name">Author</a>'
        '<span class="time-ago" data-timestamp="2026-10-02T22:12:46Z"></span></div>'
        f'<div class="description">Body</div>{body}</div>',
        "html.parser",
    )


def test_proxy_file_attachment_is_named_from_its_own_link():
    # Layout observed live 2026-10-08: the generic nav-pill "Download File" and
    # the named per-file link both point at the same proxy path. The name must
    # come from the per-file link, not the pill, regardless of document order.
    soup = _page(
        '<ul class="nav-pills"><li><a aria-label="Download File" href="/feeds/1/attachment/2">'
        '<i class="fa fa-download"></i> Download File</a></li></ul>'
        '<div><a aria-label="Download Board Agenda.pdf" href="/feeds/1/attachment/2">'
        "<i class='fa fa-download'></i> Board Agenda.pdf</a></div>"
    )
    detail = parse_post_detail(soup)
    assert [(a.name, a.url, a.file_type) for a in detail.attachments] == [
        ("Board Agenda.pdf", "/feeds/1/attachment/2", "document")
    ]


def test_s3_file_attachment_still_parses():
    href = (
        "https://psq.s3.amazonaws.com/flyer.pdf"
        "?response-content-disposition=attachment%3B%20filename%3D%22Spring%20Flyer.pdf%22"
    )
    soup = _page(f'<ul class="nav-pills"><li><a href="{href}">Download File</a></li></ul>')
    detail = parse_post_detail(soup)
    assert [(a.name, a.file_type) for a in detail.attachments] == [("Spring Flyer.pdf", "document")]
