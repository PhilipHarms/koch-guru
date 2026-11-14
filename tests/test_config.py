import pytest

from koch_guru.config import ConfigError, load_settings

BASE = {
    "TELEGRAM_TOKEN": "123:abc",
    "NOTION_TOKEN": "secret",
    "NOTION_DATABASE_ID": "db",
    "ANTHROPIC_API_KEY": "sk-ant",
}


def test_defaults():
    s = load_settings(BASE)
    assert s.anthropic_model == "claude-sonnet-5-5"
    assert s.anthropic_effort == "medium"
    assert s.allowed_user_ids == frozenset()
    assert s.properties.link == "Link"


def test_missing_variables_are_listed():
    with pytest.raises(ConfigError) as exc:
        load_settings({"TELEGRAM_TOKEN": "x"})
    for name in ("NOTION_TOKEN", "NOTION_DATABASE_ID", "ANTHROPIC_API_KEY"):
        assert name in str(exc.value)


def test_user_ids_parsing():
    s = load_settings({**BASE, "ALLOWED_USER_IDS": " 1, 22 ;333 ,"})
    assert s.allowed_user_ids == {1, 22, 333}


def test_invalid_user_id():
    with pytest.raises(ConfigError):
        load_settings({**BASE, "ALLOWED_USER_IDS": "philip"})


def test_invalid_effort():
    with pytest.raises(ConfigError):
        load_settings({**BASE, "ANTHROPIC_EFFORT": "turbo"})
