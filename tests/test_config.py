import pytest

from koch_guru.config import ConfigError, load_settings

BASE = {
    "TELEGRAM_TOKEN": "123:abc",
    "NOTION_TOKEN": "secret",
    "NOTION_DATABASE_ID": "db",
    "OPENROUTER_API_KEY": "sk-or",
}


def test_defaults():
    s = load_settings(BASE)
    assert s.model == "anthropic/claude-sonnet-5.5"
    assert s.allowed_user_ids == frozenset()
    assert s.properties.link == "Link"


def test_missing_variables_are_listed():
    with pytest.raises(ConfigError) as exc:
        load_settings({"TELEGRAM_TOKEN": "x"})
    for name in ("NOTION_TOKEN", "NOTION_DATABASE_ID", "OPENROUTER_API_KEY"):
        assert name in str(exc.value)


def test_user_ids_parsing():
    s = load_settings({**BASE, "ALLOWED_USER_IDS": " 1, 22 ;333 ,"})
    assert s.allowed_user_ids == {1, 22, 333}


def test_invalid_user_id():
    with pytest.raises(ConfigError):
        load_settings({**BASE, "ALLOWED_USER_IDS": "philip"})


def test_hint_when_old_variable_name_is_used():
    env = {k: v for k, v in BASE.items() if k != "OPENROUTER_API_KEY"} | {"ANTHROPIC_API_KEY": "sk-or"}
    with pytest.raises(ConfigError) as exc:
        load_settings(env)
    assert "umbenennen" in str(exc.value)


def test_model_override():
    assert load_settings({**BASE, "OPENROUTER_MODEL": "anthropic/claude-haiku-5.5"}).model.endswith("haiku-5.5")


KEY_A, KEY_B = "a" * 32, "B-_9" * 8


def test_app_users_and_port():
    s = load_settings({**BASE, "APP_USERS": f" Philip:{KEY_A} , charlotte:{KEY_B} ", "PORT": "8080"})
    assert s.app_users == {KEY_A: "philip", KEY_B: "charlotte"}
    assert s.port == 8080
    assert load_settings(BASE).app_users == {} and load_settings(BASE).port == 8000
    assert s.app_users_error is None


@pytest.mark.parametrize("raw", [
    "philip",                         # no key
    f":{KEY_A}",                      # no name
    "philip:kurz",                    # key too short
    "philip:" + "ä" * 30,             # not URL-safe
    f"philip:{KEY_A},charlotte:{KEY_A}",  # same key twice
    f"philip:{KEY_A},philip:{KEY_B}",     # same name twice
])
def test_invalid_app_users_disable_web_login_but_keep_the_bot_running(raw):
    s = load_settings({**BASE, "APP_USERS": raw})
    assert s.app_users == {}
    assert s.app_users_error and s.app_users_error.startswith("APP_USERS")
    assert KEY_A not in s.app_users_error  # never echo a secret into the logs


def test_invalid_port():
    with pytest.raises(ConfigError):
        load_settings({**BASE, "PORT": "achtzig"})
