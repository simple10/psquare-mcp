"""Synthetic group fixtures; no production people, cookies, or CSRF tokens."""

import asyncio
import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
import requests
from bs4 import BeautifulSoup

from parentsquare_mcp import server
from parentsquare_mcp.models import GroupMemberSelection
from parentsquare_mcp.parsers.groups import (
    build_add_group_members_body,
    extract_group_member_selection,
    parse_group_members_page,
    parse_group_selectable_user_ids,
)


def directory(roles, *, total=None, next_page=None, students=0):
    def person(user_id, role):
        link = f'<a href="/schools/7/users/{user_id}">Person {user_id}</a>'
        if role in ("owner", "manager"):
            return f'<div class="manage-box">{link}</div>'
        return (
            f'<tr class="manage-box"><th>{link}</th><td>'
            f'<a data-method="post" href="/groups/9/remove_user?member={user_id}">Remove</a>'
            '</td></tr>'
        )

    tables = ""
    for role, label in (("member", "Staff and Parent Members"), ("guest", "Guest Users")):
        rows = "".join(person(u, r) for u, r in roles.items() if r == role)
        if rows:
            tables += (
                f'<table class="table table-striped"><thead><tr><th>{label}</th></tr></thead>'
                f'<tbody>{rows}</tbody></table>'
            )
    pagination = (
        f'<a rel="next" href="/groups/9/users?member_page={next_page}">Next</a>'
        if next_page is not None else ""
    )
    return f"""
    <div id="user-index-main" data-context="Group" data-institute-id="7">
      <table class="stats"><tr>
        <td class="stat"><div class="number">{len(roles) if total is None else total}</div><div>Members</div></td>
        <td class="stat"><div class="number">{students}</div><div>Students</div></td>
      </tr></table>
      <div class="school-directory"><div class="group-directory">
        <div class="panel-heading">Fixture Group <div>Manage</div></div>
        <a href="/groups/9/users/export">Export CSV</a>
        <table><thead>
          <tr class="owners-row"><th>Group Owners</th><th>
            {''.join(person(u, r) for u, r in roles.items() if r == 'owner')}
          </th></tr>
          <tr class="managers-row"><th>Group Managers</th><th>
            {''.join(person(u, r) for u, r in roles.items() if r == 'manager')}
          </th></tr>
        </thead></table></div>{tables}
        <nav aria-label="Pagination">{pagination}</nav>
      </div>
    </div>
    """


def selection(member_ids=(2,), student_ids=(), group_type="CsvGroup"):
    return f"""
    <form id="all-group-form" action="/groups/9" method="post">
      <input name="_method" value="patch">
      <input name="group_type" value="{group_type}">
      <input name="group[csv_student_id]">
      <input name="group[csv_staff_id]">
      <input name="external_csv_upload">
      <input name="group[member_tokens]" value="{','.join(map(str, member_ids))}">
      <input name="group[student_tokens]" value="{','.join(map(str, student_ids))}">
      <input name="group[group_user_associations_attributes][0][user_attributes][first_name]">
      <input name="group[group_user_associations_attributes][0][user_attributes][last_name]">
      <input name="group[group_user_associations_attributes][0][user_attributes][email]">
      <input name="group[group_user_associations_attributes][0][role]" value="EXTERNAL">
      <input name="group[group_user_associations_attributes][0][_destroy]" value="false">
      <input name="group[group_user_associations_attributes][0][_destroy]" value="false">
      <input name="add_people_update" value="Save">
    </form>
    """


def soup(html):
    return BeautifulSoup(html, "html.parser")


def test_directory_distinguishes_owners_managers_members_guests():
    page = parse_group_members_page(soup(directory({1: "owner", 2: "member", 3: "guest", 4: "manager"})), 9)
    assert page.name == "Fixture Group"
    assert page.total_count == 4
    assert page.school_id == 7
    assert {m.user_id: m.role for m in page.members} == {1: "owner", 2: "member", 3: "guest", 4: "manager"}
    assert {m.user_id for m in page.members if m.removable} == {2, 3}


@pytest.mark.parametrize("html", [
    "<html>Sign in</html>",
    directory({1: "owner"}).replace("Members", "Other"),
    directory({1: "owner"}).replace("owners-row", "unknown"),
    directory({1: "owner"}).replace("/groups/9/users/export", "/groups/8/users/export"),
    directory({1: "owner"}, next_page=2).replace(
        "/groups/9/users?member_page=2", "https://elsewhere.invalid/groups/9/users?member_page=2",
    ),
])
def test_directory_rejects_unrecognized_or_incomplete_structure(html):
    with pytest.raises(ValueError):
        parse_group_members_page(soup(html), 9)


def test_selection_preserves_exact_user_and_student_lists():
    current = extract_group_member_selection(soup(selection((2, 5), (10, 11))), 9)
    assert current == GroupMemberSelection([2, 5], [10, 11])
    body = build_add_group_members_body(current, [6, 6])
    assert body["group[member_tokens]"] == "2,5,6"
    assert body["group[student_tokens]"] == "10,11"
    assert body["group[group_user_associations_attributes][0][_destroy]"] == ["false", "false"]
    assert "new_owner_ids" not in body
    assert "allow_guest_member_manual" not in body
    assert "group[name]" not in body


@pytest.mark.parametrize("html", [
    selection().replace('name="group[member_tokens]"', 'name="missing"'),
    selection().replace('value="2"', 'value="2,2"'),
    selection().replace('value="2"', 'value="not-an-id"'),
    selection().replace('name="group[member_tokens]"', 'disabled name="group[member_tokens]"'),
    selection(group_type="AutoGroup"),
    selection().replace('name="external_csv_upload"', 'name="external_csv_upload" value="pending"'),
    selection().replace('action="/groups/9"', 'action="/groups/8"'),
    selection().replace('[first_name]">', '[first_name]" value="Unexpected">'),
    selection().replace('value="false"', 'value="true"', 1),
    selection().replace("</form>", '<input type="checkbox" name="enabled" checked></form>'),
])
def test_selection_refuses_unknown_state_instead_of_clearing_it(html):
    with pytest.raises(ValueError):
        extract_group_member_selection(soup(html), 9)


def test_empty_selection_is_not_reconstructed_from_owners_or_guests():
    assert extract_group_member_selection(soup(selection(())), 9).member_ids == []


def test_unchecked_optional_checkbox_is_not_a_submitted_field():
    html = selection().replace("</form>", '<input type="checkbox" name="enabled"></form>')
    assert extract_group_member_selection(soup(html), 9).member_ids == [2]


def test_picker_requires_complete_known_shape():
    assert parse_group_selectable_user_ids({"data": [["", 2, "Person 2", "Parent"]]}) == {2}
    for data in ({}, [], {"data": [{"id": 2}]}, {"data": [["", None, "Person", ""]]}):
        with pytest.raises(ValueError):
            parse_group_selectable_user_ids(data)


class FakeClient:
    def __init__(self):
        self.roles = {1: "owner", 2: "member", 3: "guest", 4: "manager"}
        self.selected = [2]
        self.students = []
        self.writes = []
        self.pages = None
        self.status = 200
        self.apply = True
        self.break_readback = False
        self.collateral = False
        self.timeout = False
        self.guest_users = {3, 7}
        self.available = {2, 3, 5, 6, 7}

    def get_page(self, path, params=None):
        if self.break_readback and self.writes:
            raise requests.ConnectionError("read failed")
        if path == "/groups/9/add_people":
            return soup(selection(self.selected, self.students))
        assert path == "/groups/9/users"
        if self.pages:
            return soup(self.pages[(params or {}).get("member_page", 1)])
        return soup(directory(self.roles, students=len(self.students)))

    def get_json(self, path, params=None):
        assert path == "/schools/7/selection_users"
        assert params == {"group_id": 9}
        return {"data": [["", u, f"Person {u}", ""] for u in self.available]}

    def post_form(self, path, body, *, html_response=False):
        assert html_response is True
        self.writes.append((path, deepcopy(body)))
        if self.apply:
            if "/remove_user" in path:
                user_id = int(path.split("member=")[1])
                self.roles.pop(user_id)
                self.selected = [u for u in self.selected if u != user_id]
            else:
                assert path == "/groups/9"
                requested = [int(u) for u in body["group[member_tokens]"].split(",")]
                for user_id in requested:
                    self.roles.setdefault(user_id, "guest" if user_id in self.guest_users else "member")
                self.selected = [u for u in requested if self.roles[u] != "guest"]
            if self.collateral:
                self.roles.pop(1, None)
        if self.timeout:
            raise requests.Timeout("write timed out")
        return SimpleNamespace(status_code=self.status, text="<html>Directory</html>")


@pytest.fixture
def fixture(monkeypatch, tmp_path):
    monkeypatch.setenv("PS_ENABLE_WRITES", "1")
    monkeypatch.setenv("PS_AUDIT_LOG", str(tmp_path / "audit.jsonl"))
    client = FakeClient()
    app = server.AppContext(client=client, download_dir=tmp_path)
    context = SimpleNamespace(request_context=SimpleNamespace(lifespan_context=app))
    return client, context


@pytest.mark.parametrize("changes,member_ids,removing", [
    ({5: "member"}, [2, 5], False),
    ({7: "guest"}, [2], False),
    ({5: "member", 7: "guest"}, [2, 5], False),
    ({2: None, 3: None}, [], True),
])
def test_group_verification_is_pure_and_handles_cumulative_changes(
    fixture, changes, member_ids, removing,
):
    client, _ = fixture
    client.students = [10, 11] if not removing else []
    before, selection_before = server._read_group_state(client, 9)
    for user_id, role in changes.items():
        if role is None:
            client.roles.pop(user_id)
        else:
            client.roles[user_id] = role
    client.selected = member_ids
    after, selection_after = server._read_group_state(client, 9)
    states = (before, selection_before, after, selection_after)
    unchanged = deepcopy(states)

    for _ in range(2):
        assert server._verify_group_change(
            *states, list(changes), removing=removing,
        ) is None
        assert states == unchanged


@pytest.mark.parametrize("target,field,value,diagnostic", [
    ("group", "school_id", 8, "Group identity or student count changed"),
    ("group", "name", "Changed", "Group identity or student count changed"),
    ("group", "student_count", 3, "Group identity or student count changed"),
    ("selection", "member_ids", [2], "Saved user selections differ"),
    ("selection", "student_ids", [11, 10], "Saved student selections changed"),
    ("owner", "role", "member", "Existing roles were not preserved for user_ids: [1]"),
    ("addition", "role", "owner", "Added user_ids lack member/guest roles: [5]"),
])
def test_group_verification_explains_unrelated_changes(fixture, target, field, value, diagnostic):
    client, _ = fixture
    client.students = [10, 11]
    before, selection_before = server._read_group_state(client, 9)
    client.roles[5] = "member"
    client.selected.append(5)
    after, selection_after = server._read_group_state(client, 9)
    targets = {
        "group": after, "selection": selection_after,
        "owner": after.members[0], "addition": next(m for m in after.members if m.user_id == 5),
    }
    setattr(targets[target], field, value)

    mismatch = server._verify_group_change(
        before, selection_before, after, selection_after, [5], removing=False,
    )
    assert diagnostic in mismatch


@pytest.mark.parametrize("after_write", [False, True])
def test_missing_selection_blocks_write_or_reports_unknown_outcome(fixture, monkeypatch, after_write):
    client, context = fixture
    original = client.get_page

    def get_page(path, params=None):
        if path.endswith("/add_people") and (not after_write or client.writes):
            return soup("<html>Unexpected form</html>")
        return original(path, params)

    monkeypatch.setattr(client, "get_page", get_page)
    result = asyncio.run(server.add_group_members(9, [5], context=context))
    assert len(client.writes) == (1 if after_write else 0)
    assert ("outcome is unknown" if after_write else "No write attempted") in result


def test_list_is_ungated_and_reads_all_pages(fixture, monkeypatch):
    client, context = fixture
    monkeypatch.setenv("PS_ENABLE_WRITES", "0")
    client.pages = {
        1: directory({1: "owner", 2: "member"}, total=3, next_page=2),
        2: directory({1: "owner", 3: "guest"}, total=3),
    }
    result = asyncio.run(server.list_group_members(9, context=context))
    assert result["count"] == 3
    assert {m["user_id"] for m in result["members"]} == {1, 2, 3}


@pytest.mark.parametrize("pages", [
    {1: directory({1: "owner"}, total=3)},
    {1: directory({1: "owner"}, total=2, next_page=1)},
    {1: directory({1: "owner"}, total=2, next_page=1001)},
    {1: directory({1: "owner"}, total=2, next_page=2), 2: directory({1: "owner"}, total=2)},
    {1: directory({1: "owner"}, total=2, next_page=2), 2: directory({1: "owner", 2: "member"}, total=3)},
])
def test_incomplete_reads_block_writes(fixture, pages):
    client, context = fixture
    client.pages = pages
    result = asyncio.run(server.add_group_members(9, [5], context=context))
    assert result.startswith("❌")
    assert client.writes == []


def test_add_preserves_unrelated_people_and_student_selections(fixture):
    client, context = fixture
    client.students = [10]
    result = asyncio.run(server.add_group_members(9, [5, 6, 5, 2, 3, 1], context=context))
    assert result.startswith("✅")
    assert len(client.writes) == 1
    body = client.writes[0][1]
    assert body["group[member_tokens]"] == "2,5,6"
    assert body["group[student_tokens]"] == "10"
    assert client.roles == {1: "owner", 2: "member", 3: "guest", 4: "manager", 5: "member", 6: "member"}


def test_remove_targets_each_person_without_replacing_the_group(fixture):
    client, context = fixture
    result = asyncio.run(server.remove_group_members(9, [2, 3, 2, 100], context=context))
    assert result.startswith("✅")
    assert [p for p, _ in client.writes] == [
        "/groups/9/remove_user?member=2", "/groups/9/remove_user?member=3",
    ]
    assert all(b == {"_method": "post"} for _, b in client.writes)
    assert client.roles == {1: "owner", 4: "manager"}


@pytest.mark.parametrize("targets,selected", [([7], [2]), ([5, 7], [2, 5])])
def test_add_existing_guests_are_verified_outside_saved_user_tokens(fixture, targets, selected):
    client, context = fixture
    baseline = dict(client.roles)
    result = asyncio.run(server.add_group_members(9, targets, context=context))
    assert result.startswith("✅")
    assert client.roles[7] == "guest"
    assert all(client.roles[u] == role for u, role in baseline.items())
    assert client.selected == selected
    assert "7" in client.writes[0][1]["group[member_tokens]"].split(",")


def test_guest_remove_and_readd_restores_exact_original_state(fixture):
    client, context = fixture
    baseline_roles = dict(client.roles)
    baseline_selection = list(client.selected)
    assert asyncio.run(server.remove_group_members(9, [3], context=context)).startswith("✅")
    assert 3 not in client.roles
    assert asyncio.run(server.add_group_members(9, [3], context=context)).startswith("✅")
    assert client.roles == baseline_roles
    assert client.selected == baseline_selection


def test_guest_add_still_requires_the_guest_to_appear_in_the_directory(fixture):
    client, context = fixture
    client.apply = False
    result = asyncio.run(server.add_group_members(9, [7], context=context))
    assert result.startswith("⚠️")
    assert "Missing expected user_ids: [7]" in result


def test_ordinary_member_add_still_requires_saved_user_token(fixture, monkeypatch):
    client, context = fixture
    original = client.post_form

    def post(*args, **kwargs):
        response = original(*args, **kwargs)
        client.selected.remove(5)
        return response

    monkeypatch.setattr(client, "post_form", post)
    result = asyncio.run(server.add_group_members(9, [5], context=context))
    assert result.startswith("⚠️")
    assert client.roles[5] == "member"


@pytest.mark.parametrize("tool,ids", [
    (server.add_group_members, []),
    (server.remove_group_members, []),
    (server.add_group_members, [-1]),
    (server.add_group_members, [True]),
    (server.add_group_members, [100]),
    (server.remove_group_members, [2, 1]),
    (server.remove_group_members, [4]),
])
def test_invalid_targets_and_protected_roles_block_whole_call(fixture, tool, ids):
    client, context = fixture
    result = asyncio.run(tool(9, ids, context=context))
    assert result.startswith("❌")
    assert client.writes == []


def test_student_derived_removal_is_refused(fixture):
    client, context = fixture
    client.students = [10]
    assert asyncio.run(server.remove_group_members(9, [2], context=context)).startswith("❌")
    assert not client.writes


@pytest.mark.parametrize("tool,ids", [
    (server.add_group_members, [1, 2, 3, 4]),
    (server.remove_group_members, [100]),
])
def test_noop_is_audited_without_a_write(fixture, tool, ids, tmp_path):
    client, context = fixture
    assert "No change" in asyncio.run(tool(9, ids, context=context))
    assert not client.writes
    event = json.loads((tmp_path / "audit.jsonl").read_text())
    assert event["ok"] is True


@pytest.mark.parametrize("tool", [server.add_group_members, server.remove_group_members])
def test_disabled_writes_are_audited_without_network(fixture, monkeypatch, tool, tmp_path):
    client, context = fixture
    monkeypatch.setenv("PS_ENABLE_WRITES", "0")
    client.get_page = lambda *a, **kw: pytest.fail("Gate must prevent reads too")
    result = asyncio.run(tool(9, [2], context=context))
    assert result == server.WRITES_DISABLED_MESSAGE
    assert json.loads((tmp_path / "audit.jsonl").read_text())["ok"] is False


@pytest.mark.parametrize("failure", ["apply", "break_readback", "collateral"])
def test_failure_or_unknown_readback_stops_removal_batch(fixture, failure):
    client, context = fixture
    setattr(client, failure, failure != "apply")
    result = asyncio.run(server.remove_group_members(9, [2, 3], context=context))
    assert result.startswith("⚠️")
    assert len(client.writes) == 1
    assert "do not retry" in result.lower()


@pytest.mark.parametrize("status", [422, 500])
def test_http_errors_are_reported_even_if_membership_changed(fixture, status):
    client, context = fixture
    client.status = status
    result = asyncio.run(server.remove_group_members(9, [2, 3], context=context))
    assert result.startswith("⚠️")
    assert str(status) in result
    assert len(client.writes) == 1


def test_write_timeout_is_verified_without_replaying(fixture):
    client, context = fixture
    client.timeout = True
    result = asyncio.run(server.add_group_members(9, [5], context=context))
    assert "verified" in result and "timed out" in result
    assert len(client.writes) == 1
    assert 5 in client.roles


def test_partial_removal_reports_completed_ids_and_stops(fixture, monkeypatch):
    client, context = fixture
    original = client.post_form

    def post(*args, **kwargs):
        if client.writes:
            client.apply = False
            client.status = 422
        return original(*args, **kwargs)

    monkeypatch.setattr(client, "post_form", post)
    result = asyncio.run(server.remove_group_members(9, [2, 3], context=context))
    assert result.startswith("⚠️")
    assert "Previously verified user_ids: [2]" in result
    assert "HTTP 422" in result
    assert 2 not in client.roles and 3 in client.roles


def test_mcp_schemas_expose_required_identifiers_without_context():
    wanted = {"list_group_members", "add_group_members", "remove_group_members"}
    tools = [t for t in asyncio.run(server.mcp.list_tools()) if t.name in wanted]
    assert len(tools) == 3
    for tool in tools:
        schema = tool.input_schema
        assert schema["properties"]["group_id"]["type"] == "integer"
        assert "context" not in schema["properties"]
        assert set(schema["required"]) == (
            {"group_id"} if tool.name == "list_group_members" else {"group_id", "user_ids"}
        )


def test_membership_tools_share_the_existing_global_lock(fixture, monkeypatch):
    client, context = fixture
    app = context.request_context.lifespan_context
    original_read = server._group_read
    original_readback = server._readback
    readback_entered = asyncio.Event()
    release_readback = asyncio.Event()
    active = 0
    maximum = 0

    async def slow_read(*args):
        nonlocal active, maximum
        assert app.section_membership_write_lock.locked()
        active += 1
        maximum = max(maximum, active)
        await asyncio.sleep(0.01)
        result = await original_read(*args)
        active -= 1
        return result

    async def paused_readback(*args):
        assert app.section_membership_write_lock.locked()
        if len(client.writes) == 1:
            readback_entered.set()
            await release_readback.wait()
        return await original_readback(*args)

    monkeypatch.setattr(server, "_group_read", slow_read)
    monkeypatch.setattr(server, "_readback", paused_readback)

    async def run():
        async with server._section_membership_write_lock(app):
            first = asyncio.create_task(server.add_group_members(9, [5], context=context))
            second = asyncio.create_task(server.add_group_members(9, [6], context=context))
            await asyncio.sleep(0.02)
            assert client.writes == []
        await asyncio.wait_for(readback_entered.wait(), timeout=1)
        assert len(client.writes) == 1
        assert not second.done()
        release_readback.set()
        return await asyncio.gather(first, second)

    results = asyncio.run(run())
    assert all(r.startswith("✅") for r in results)
    assert maximum == 1
    assert set(client.selected) == {2, 5, 6}
