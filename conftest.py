"""Shared test fixtures and path setup."""

import dataclasses
import os
import sys
import tempfile

# Redirect the DEFAULT database to a temp file BEFORE config is imported, so
# code paths that fall back to settings.db_path (cost ledger, budget checks)
# can never touch a real agent.db during tests.
os.environ.setdefault("DB_PATH", os.path.join(tempfile.gettempdir(), "pulse-test-default.db"))

import pytest  # noqa: E402

sys.path.insert(0, os.path.dirname(__file__))

from pipeline import memory  # noqa: E402


def patch_settings(monkeypatch, module, **overrides):
    """Settings is a frozen dataclass, so tests swap the module-level reference
    for a modified copy instead of mutating it."""
    monkeypatch.setattr(module, "settings",
                        dataclasses.replace(module.settings, **overrides))


@pytest.fixture()
def temp_db():
    """A fresh, schema-initialized SQLite file, torn down after the test."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    memory.init_db(db_path=path)
    yield path
    try:
        os.remove(path)
    except OSError:
        pass


# ---- A minimal stub of the Anthropic client (mirrors msg.content[*].text) ----
class _Block:
    def __init__(self, text):
        self.text = text


class _Msg:
    def __init__(self, text):
        self.content = [_Block(text)]


class StubMessages:
    def __init__(self, payload):
        self._payload = payload
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _Msg(self._payload)


class StubClient:
    """Returns a fixed payload string from messages.create, like the real SDK."""

    def __init__(self, payload):
        self.messages = StubMessages(payload)
