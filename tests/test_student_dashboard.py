"""Synthetic dashboard fixtures; no production content."""

import pytest
from bs4 import BeautifulSoup

from parentsquare_mcp.parsers.students import parse_student_dashboard


@pytest.mark.parametrize("tag", ["h1", "h3"])
def test_student_name_heading_level(tag):
    # The name heading was h3; observed live as h1 on 2026-10-08.
    soup = BeautifulSoup(
        f'<div class="student-info-name-container"><{tag}><a href="/students/1/dashboard">'
        f"Student Name</a></{tag}><div>5th Grade</div></div>",
        "html.parser",
    )
    d = parse_student_dashboard(soup)
    assert d.student_name == "Student Name"
    assert d.grade == "5th Grade"
