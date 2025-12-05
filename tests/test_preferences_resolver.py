import os

import pytest

os.environ.setdefault("USERS_TABLE", "Users")
os.environ.setdefault("MANAGED_PREFERENCES_TABLE", "ManagedPreferenceSchema")
os.environ.setdefault("AGE_THRESHOLDS_TABLE", "AgeThresholds")

from lib.preferences_resolver import ensure_preference_value_allowed, merge_preferences


def test_merge_preferences_preserves_user_values_and_adds_defaults():
    user_items = [
        {"preferenceKey": "language", "value": "en"},
    ]
    defaults = {
        "language": {
            "preferenceKey": "language",
            "value": "en",
            "source": "baseDefault",
            "resolved": True,
            "isManaged": True,
            "isSet": False,
        },
        "voice_chat": {
            "preferenceKey": "voice_chat",
            "value": "off",
            "source": "childOverride",
            "resolved": True,
            "isManaged": True,
            "isSet": False,
        },
    }

    merged = merge_preferences(user_items, defaults, include_defaults=True)

    assert any(item["preferenceKey"] == "language" and item["isSet"] for item in merged)
    voice_chat = next(item for item in merged if item["preferenceKey"] == "voice_chat")
    assert voice_chat["value"] == "off"
    assert voice_chat["isManaged"] is True
    assert voice_chat["isSet"] is False


def test_ensure_preference_value_allowed_blocks_locked_child():
    schema = {"preferenceKey": "voice_chat", "childOverride": "locked"}
    user_ctx = {"is_child": True, "age": 12}

    with pytest.raises(PermissionError):
        ensure_preference_value_allowed(schema, user_ctx, "on")


def test_ensure_preference_value_allowed_blocks_below_min_age():
    schema = {"preferenceKey": "voice_chat", "minAge": 13}
    user_ctx = {"is_child": True, "age": 10}

    with pytest.raises(PermissionError):
        ensure_preference_value_allowed(schema, user_ctx, "on")


def test_ensure_preference_value_allowed_allows_valid_change():
    schema = {"preferenceKey": "voice_chat", "minAge": 10}
    user_ctx = {"is_child": True, "age": 12}

    # Should not raise
    ensure_preference_value_allowed(schema, user_ctx, "on")

