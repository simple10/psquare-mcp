"""Synthetic feed-list fixtures; no production content."""

from bs4 import BeautifulSoup

from parentsquare_mcp.parsers.feeds import parse_feed_page
from parentsquare_mcp.parsers.polls import parse_polls_page


def _post(feed_id: int, title: str) -> str:
    return (
        '<div class="ps-box"><div class="feed">'
        f'<div id="feed_{feed_id}"><div class="feed-show">'
        f'<div class="feed-title"><div class="subject"><a><span role="heading">{title}</span></a></div></div>'
        '<div class="feed-metadata"><a class="user-name">Author</a>'
        '<span class="time-ago" data-timestamp="2026-10-05T16:39:06Z"></span></div>'
        '<div class="description truncated-text">Body</div>'
        "</div></div></div></div>"
    )


def _poll(feed_id: int) -> str:
    return (
        '<div class="ps-box"><div class="feed">'
        f'<div id="feed_{feed_id}"><div class="feed-show">'
        '<div class="feed-title"><div class="subject"><a>Question?</a></div></div>'
        '<div class="feed-metadata"><a class="user-name">Author</a>'
        '<span class="time-ago" data-timestamp="2026-10-05T16:39:06Z"></span></div>'
        '<div class="poll-option"><input aria-label="Yes"><span class="num-votes">3</span></div>'
        "</div></div></div></div>"
    )


def _legacy(*boxes: str) -> BeautifulSoup:
    return BeautifulSoup(f'<div id="feeds-list">{"".join(boxes)}</div>', "html.parser")


def _current(*boxes: str) -> BeautifulSoup:
    """Layout observed live on 2026-10-08: each post sits in ul.feeds-list > li.feeds-list-item."""
    items = "".join(
        f'<li class="feeds-list-item">{b}<div id="feed-admins-manage-list-{i}" class="hidden"></div></li>'
        for i, b in enumerate(boxes)
    )
    return BeautifulSoup(f'<div id="feeds-list"><ul class="feeds-list">{items}</ul></div>', "html.parser")


def test_feed_page_legacy_layout_still_parses():
    posts = parse_feed_page(_legacy(_post(1, "One"), _post(2, "Two")))
    assert [(p.id, p.title) for p in posts] == [(1, "One"), (2, "Two")]


def test_feed_page_list_item_layout_parses():
    posts = parse_feed_page(_current(_post(1, "One"), _post(2, "Two")))
    assert [(p.id, p.title) for p in posts] == [(1, "One"), (2, "Two")]
    assert posts[0].author == "Author"
    assert posts[0].summary == "Body"


def test_feed_page_ignores_boxes_without_feed_id():
    posts = parse_feed_page(_current('<div class="ps-box">sidebar</div>', _post(5, "Five")))
    assert [p.id for p in posts] == [5]


def test_polls_page_list_item_layout_parses():
    polls = parse_polls_page(_current(_poll(9)))
    assert [p.id for p in polls] == [9]
    assert polls[0].options and polls[0].options[0].votes == 3
