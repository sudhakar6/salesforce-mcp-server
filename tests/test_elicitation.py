from __future__ import annotations

from salesforce_mcp.elicitation import confirm, soql_looks_unscoped, sosl_looks_unscoped
from tests.conftest import FakeContext


def test_soql_unscoped_when_no_where_and_no_limit():
    assert soql_looks_unscoped("SELECT Id FROM Account") is True


def test_soql_unscoped_when_where_but_no_limit():
    assert soql_looks_unscoped("SELECT Id FROM Account WHERE Name = 'Acme'") is True


def test_soql_unscoped_when_limit_but_no_where():
    assert soql_looks_unscoped("SELECT Id FROM Account LIMIT 10") is True


def test_soql_scoped_when_where_and_limit_present():
    assert soql_looks_unscoped("SELECT Id FROM Account WHERE Name = 'Acme' LIMIT 10") is False


def test_sosl_unscoped_when_no_returning_and_no_limit():
    assert sosl_looks_unscoped("FIND {Acme} IN ALL FIELDS") is True


def test_sosl_unscoped_when_returning_but_no_limit():
    assert sosl_looks_unscoped("FIND {Acme} IN ALL FIELDS RETURNING Account(Name)") is True


def test_sosl_scoped_when_returning_and_limit_present():
    assert sosl_looks_unscoped("FIND {Acme} IN ALL FIELDS RETURNING Account(Name LIMIT 5)") is False


async def test_confirm_disabled_always_proceeds_without_touching_ctx():
    ctx = FakeContext(action="decline")
    assert await confirm(ctx, "proceed?", enabled=False) is True
    assert ctx.messages == []


async def test_confirm_enabled_accept_with_proceed_true():
    ctx = FakeContext(action="accept", proceed=True)
    assert await confirm(ctx, "proceed?", enabled=True) is True
    assert ctx.messages == ["proceed?"]


async def test_confirm_enabled_accept_with_proceed_false():
    ctx = FakeContext(action="accept", proceed=False)
    assert await confirm(ctx, "proceed?", enabled=True) is False


async def test_confirm_enabled_decline():
    ctx = FakeContext(action="decline")
    assert await confirm(ctx, "proceed?", enabled=True) is False


async def test_confirm_enabled_cancel():
    ctx = FakeContext(action="cancel")
    assert await confirm(ctx, "proceed?", enabled=True) is False
