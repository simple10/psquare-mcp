from __future__ import annotations

import re
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup

from parentsquare_mcp.models import (
    FeedPost,
    Group,
    GroupMember,
    GroupMembersPage,
    GroupMemberSelection,
)


def parse_groups_list(soup: BeautifulSoup) -> list[Group]:
    """Parse /schools/{id}/groups -> list of Group.

    This is a React-rendered page with Tailwind CSS classes.
    Strategy: Find group links by href pattern /groups/{id}/feeds and
    extract surrounding data (name, member count, etc.)

    Structure:
      #react-app-root
        a[href*=/groups/][href*=/feeds]  (group name links)
        a[href*=/groups/][href*=/users]  (member count links, text="{N} Users")
    """
    groups: list[Group] = []

    # Find all group name links
    group_links = soup.find_all("a", href=re.compile(r"/groups/\d+/feeds"))
    seen_ids: set[int] = set()

    for link in group_links:
        href = link.get("href", "")
        id_match = re.search(r"/groups/(\d+)/feeds", href)
        if not id_match:
            continue
        group_id = int(id_match.group(1))
        if group_id in seen_ids:
            continue
        seen_ids.add(group_id)

        name = link.get_text(strip=True)

        # Find the containing element for this group
        # Walk up to find sibling/nearby elements with stats
        container = link
        for _ in range(8):
            if container.parent:
                container = container.parent
            else:
                break

        # Member count — look for users link nearby
        member_count = 0
        users_link = container.find("a", href=re.compile(rf"/groups/{group_id}/users"))
        if users_link:
            count_match = re.search(r"(\d+)\s*Users?", users_link.get_text())
            if count_match:
                member_count = int(count_match.group(1))

        # Description — not always present, look for descriptive text nearby
        description = None

        groups.append(
            Group(
                id=group_id,
                name=name,
                member_count=member_count,
                description=description,
            )
        )

    return groups


def parse_group_feed(soup: BeautifulSoup) -> list[FeedPost]:
    """Parse /schools/{id}/groups/{group_id}/feeds.

    Group feeds use the same structure as the main feed.
    Reuse the feed parser.
    """
    from parentsquare_mcp.parsers.feeds import parse_feed_page

    return parse_feed_page(soup)


def _positive_id(value: object) -> int:
    if not re.fullmatch(r"[1-9]\d*", str(value)):
        raise ValueError("Missing or invalid group membership identifier.")
    return int(str(value))


def parse_group_members_page(soup: BeautifulSoup, group_id: int) -> GroupMembersPage:
    """Parse the HTML directory, including owners/managers and guest users.

    ``Members`` includes owners and guests, not just the paginated ordinary
    members. Reading only the first page or only removal links loses people.
    Keep that declared total so the caller can refuse incomplete snapshots.
    """
    root = soup.select_one('#user-index-main[data-context="Group"]')
    directory = root.select_one(".school-directory") if root else None
    heading = directory.select_one(".group-directory .panel-heading") if directory else None
    if root is None or directory is None or heading is None:
        raise ValueError("Could not recognize the group directory; membership is unknown.")
    if not directory.select_one(f'a[href="/groups/{group_id}/users/export"]'):
        raise ValueError("Could not verify the requested group directory.")
    school_id = _positive_id(root.get("data-institute-id"))
    counts = {}
    for cell in root.select("table.stats td.stat"):
        number = cell.select_one(".number")
        if number is None:
            continue
        raw = number.get_text(strip=True).replace(",", "")
        label = cell.get_text(" ", strip=True).removeprefix(number.get_text(strip=True)).strip()
        if not raw.isdecimal():
            raise ValueError("Invalid group directory count.")
        counts[label] = int(raw)
    if "Members" not in counts or "Students" not in counts:
        raise ValueError("Group directory totals are missing.")

    members = []

    def member_from_row(row, role):
        links = row.find_all("a", href=re.compile(rf"^/schools/{school_id}/users/\d+$"))
        if len(links) != 1:
            raise ValueError("Could not identify a group member unambiguously.")
        link = links[0]
        user_id = _positive_id(link["href"].rsplit("/", 1)[1])
        name = link.get_text(" ", strip=True)
        if not name:
            raise ValueError("Group member name is missing.")
        removal = row.find("a", href=f"/groups/{group_id}/remove_user?member={user_id}")
        return GroupMember(
            user_id, name, role,
            removable=role not in ("owner", "manager")
            and removal is not None and removal.get("data-method") == "post",
        )

    for selector, role in ((".owners-row", "owner"), (".managers-row", "manager")):
        container = directory.select_one(selector)
        if container is None:
            raise ValueError("Group owner/manager information is missing.")
        for row in container.select(".manage-box"):
            members.append(member_from_row(row, role))
    for table in directory.select("table.table-striped"):
        header = table.select_one("thead th")
        label = header.get_text(" ", strip=True) if header else ""
        if label not in ("Staff and Parent Members", "Guest Users"):
            raise ValueError(f"Unsupported group directory table: {label!r}.")
        for row in table.select("tbody tr"):
            members.append(member_from_row(row, "guest" if label == "Guest Users" else "member"))
    ids = [m.user_id for m in members]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate group directory members; membership is ambiguous.")

    next_pages = set()
    for link in directory.select('nav a[rel~="next"]'):
        url = urlsplit(link.get("href", ""))
        query = parse_qs(url.query)
        if url.netloc or url.path != f"/groups/{group_id}/users" or set(query) != {"member_page"}:
            raise ValueError("Unrecognized group membership pagination.")
        if len(query["member_page"]) != 1:
            raise ValueError("Ambiguous group membership pagination.")
        next_pages.add(_positive_id(query["member_page"][0]))
    if len(next_pages) > 1:
        raise ValueError("Ambiguous next group membership page.")
    return GroupMembersPage(
        name=" ".join(s.strip() for s in heading.find_all(string=True, recursive=False)).strip(),
        school_id=school_id,
        total_count=counts["Members"],
        student_count=counts["Students"],
        members=members,
        next_page=next(iter(next_pages), None),
    )


def extract_group_member_selection(soup: BeautifulSoup, group_id: int) -> GroupMemberSelection:
    """Read saved selections from Add People, never from the directory.

    CsvGroup's ``member_tokens`` is the saved *selected-user* list, not all
    effective members: owners and external guests can be absent from it.
    Likewise, ``student_tokens`` selects students' associated parents. Echo
    both exact selections when adding; never reconstruct them from the roster.
    Missing fields mean unknown state, not empty selections.
    """
    form = soup.select_one('form#all-group-form')
    if (form is None or form.get("action") != f"/groups/{group_id}"
            or form.get("method", "").lower() != "post"):
        raise ValueError("Could not load the group's Add People form.")

    def field(name):
        tags = form.find_all("input", attrs={"name": name})
        if len(tags) != 1 or tags[0].has_attr("disabled"):
            raise ValueError(f"Missing or ambiguous group field: {name}.")
        return tags[0].get("value", "")

    if field("_method") != "patch" or field("group_type") != "CsvGroup":
        raise ValueError("Membership writes support manually selected CsvGroup groups only.")
    if any(field(key) for key in ("group[csv_student_id]", "group[csv_staff_id]", "external_csv_upload")):
        raise ValueError("A group import is present; refusing to submit it as a membership edit.")
    prefix = "group[group_user_associations_attributes][0]"
    if (any(field(f"{prefix}[user_attributes][{key}]") for key in ("first_name", "last_name", "email"))
            or field(f"{prefix}[role]") != "EXTERNAL"
            or field("add_people_update") != "Save"):
        raise ValueError("The Add People form contains unexpected guest or save fields.")
    destroy = form.find_all("input", attrs={"name": f"{prefix}[_destroy]"})
    if len(destroy) != 2 or any(tag.get("value") != "false" or tag.has_attr("disabled") for tag in destroy):
        raise ValueError("Unrecognized guest-creation row; refusing to submit it.")
    known = set(build_add_group_members_body(GroupMemberSelection([], []), []))
    known.update(("utf8", "authenticity_token"))
    for tag in form.select("input[name], select[name], textarea[name]"):
        if tag.has_attr("disabled"):
            continue
        if tag.get("type") in ("checkbox", "radio") and not tag.has_attr("checked"):
            continue
        if tag["name"] not in known:
            raise ValueError(f"Unsupported group form field: {tag['name']}.")

    def ids(name):
        value = field(name)
        result = [_positive_id(part) for part in value.split(",")] if value else []
        if len(result) != len(set(result)):
            raise ValueError(f"Duplicate saved selections in {name}.")
        return result

    return GroupMemberSelection(ids("group[member_tokens]"), ids("group[student_tokens]"))


def build_add_group_members_body(selection: GroupMemberSelection, user_ids: list[int]) -> dict:
    """Match Add People's captured Rails form, preserving both selection lists.

    The blank EXTERNAL row is the browser's unfilled guest-creation row, not an
    existing membership or owner. No names, contacts, ownership, group settings,
    or guest-consent flags may be supplied through this existing-user operation.
    """
    prefix = "group[group_user_associations_attributes][0]"
    return {
        "_method": "patch",
        "group_type": "CsvGroup",
        "group[csv_student_id]": "",
        "group[csv_staff_id]": "",
        "group[student_tokens]": ",".join(map(str, selection.student_ids)),
        "group[member_tokens]": ",".join(map(str, dict.fromkeys(selection.member_ids + user_ids))),
        f"{prefix}[user_attributes][first_name]": "",
        f"{prefix}[user_attributes][last_name]": "",
        f"{prefix}[user_attributes][email]": "",
        f"{prefix}[role]": "EXTERNAL",
        f"{prefix}[_destroy]": ["false", "false"],
        "external_csv_upload": "",
        "add_people_update": "Save",
    }


def parse_group_selectable_user_ids(data: dict) -> set[int]:
    """Read the group's existing-person picker, not the guest-creation form."""
    rows = data.get("data") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise ValueError("Could not read the group's available people.")
    result = set()
    for row in rows:
        if not isinstance(row, list) or len(row) != 4:
            raise ValueError("Unrecognized group people-picker row.")
        result.add(_positive_id(row[1]))
    return result
