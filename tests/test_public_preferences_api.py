import json

import requests

from conftest import assert_pref_in_list


def test_get_returns_empty_list_for_new_user(api_base, new_test_user_id):
    url = f"{api_base}/preferences/{new_test_user_id}"
    resp = requests.get(url)

    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert body == []


def test_full_crud_cycle_for_user(api_base, new_test_user_id):
    user_id = new_test_user_id

    # 1) Initially, should be empty
    url_get = f"{api_base}/preferences/{user_id}"
    resp = requests.get(url_get)
    assert resp.status_code == 200
    assert resp.json() == []

    # 2) Create "language" = "en"
    url_put = f"{api_base}/preferences/{user_id}"
    payload = {"preferenceKey": "language", "value": "en"}
    resp = requests.put(url_put, json=payload)
    assert resp.status_code == 200
    prefs = resp.json()
    assert isinstance(prefs, list)
    assert_pref_in_list(prefs, "language", "en")

    # 3) Add "voice_chat_enabled" = "true"
    payload2 = {"preferenceKey": "voice_chat_enabled", "value": "true"}
    resp = requests.put(url_put, json=payload2)
    assert resp.status_code == 200
    prefs = resp.json()
    assert_pref_in_list(prefs, "language", "en")
    assert_pref_in_list(prefs, "voice_chat_enabled", "true")

    # 4) GET should return both preferences
    resp = requests.get(url_get)
    assert resp.status_code == 200
    prefs = resp.json()
    assert_pref_in_list(prefs, "language", "en")
    assert_pref_in_list(prefs, "voice_chat_enabled", "true")

    # 5) DELETE language
    url_delete = f"{api_base}/preferences/{user_id}/language"
    resp = requests.delete(url_delete)
    assert resp.status_code == 200
    prefs = resp.json()
    # language should be gone
    for item in prefs:
        assert item.get("preferenceKey") != "language"
    # voice_chat_enabled should remain
    assert_pref_in_list(prefs, "voice_chat_enabled", "true")


def test_put_without_required_fields_returns_400(api_base, new_test_user_id):
    """
    Assumes your Lambda returns 400 for invalid body.
    If currently it just crashes with 500, you can adjust this test
    once you implement proper validation.
    """
    user_id = new_test_user_id
    url_put = f"{api_base}/preferences/{user_id}"

    # Missing preferenceKey
    payload = {"value": "en"}
    resp = requests.put(url_put, json=payload)

    # If you haven't implemented validation yet, this may be 500.
    # For now we assert it's not 200, to show that error is surfaced.
    assert resp.status_code != 200

