import os
import uuid
import json

import pytest
import boto3
import requests


@pytest.fixture(scope="session")
def api_base():
    """
    Base URL for API Gateway, e.g.:
    https://xxxxxx.execute-api.eu-north-1.amazonaws.com/prod
    """
    base = os.getenv("API_BASE")
    if not base:
        pytest.skip("API_BASE environment variable is not set")
    return base.rstrip("/")


@pytest.fixture(scope="session")
def lambda_client():
    """
    Boto3 Lambda client for direct function invocation (/me tests).
    """
    region = os.getenv("AWS_REGION", "eu-north-1")
    return boto3.client("lambda", region_name=region)


@pytest.fixture(scope="session")
def lambda_names():
    """
    Names of Lambda functions implementing /me logic.

    These are passed via env vars so that the tests are not hard-coded
    to a particular stack deployment.
    """
    get_name = os.getenv("GET_USER_PREFS_LAMBDA")
    set_name = os.getenv("SET_USER_PREFS_LAMBDA")
    delete_name = os.getenv("DELETE_USER_PREF_LAMBDA")

    if not (get_name and set_name and delete_name):
        pytest.skip(
            "Lambda name environment variables are not set "
            "(GET_USER_PREFS_LAMBDA, SET_USER_PREFS_LAMBDA, DELETE_USER_PREF_LAMBDA)"
        )

    return {
        "get": get_name,
        "set": set_name,
        "delete": delete_name,
    }


@pytest.fixture
def new_test_user_id():
    """
    Generates a random userId for each test so that tests are isolated.
    """
    return f"test-user-{uuid.uuid4().hex[:8]}"


def assert_pref_in_list(prefs, key, value):
    """
    Helper: check that a preference (key, value) exists in the list.
    """
    for item in prefs:
        if (
            item.get("preferenceKey") == key
            and item.get("value") == value
        ):
            return
    raise AssertionError(f"Preference {key}={value!r} not found in {prefs}")

