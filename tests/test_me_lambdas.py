import json

from conftest import assert_pref_in_list


TEST_USER_SUB = "test-user-me-123"


def _invoke_lambda(lambda_client, function_name, event):
    """
    Helper: invoke Lambda with a JSON event and parse JSON response body.
    """
    resp = lambda_client.invoke(
        FunctionName=function_name,
        Payload=json.dumps(event).encode("utf-8"),
    )
    payload_bytes = resp["Payload"].read()
    result = json.loads(payload_bytes.decode("utf-8"))
    return result


def test_me_full_cycle(lambda_client, lambda_names):
    """
    Full cycle using /me semantics:
    - PUT language=fr
    - PUT voice_chat_enabled=true
    - GET all
    - DELETE language
    - GET all again
    """
    get_fn = lambda_names["get"]
    set_fn = lambda_names["set"]
    delete_fn = lambda_names["delete"]

    # 1) Ensure clean state: not strictly necessary, but we can ignore current state.

    # 2) PUT language = fr
    put_event_lang = {
        "httpMethod": "PUT",
        "rawPath": "/me/preferences",
        "requestContext": {
            "authorizer": {
                "jwt": {
                    "claims": {
                        "sub": TEST_USER_SUB,
                    }
                }
            }
        },
        "body": json.dumps({"preferenceKey": "language", "value": "fr"}),
    }
    result = _invoke_lambda(lambda_client, set_fn, put_event_lang)
    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert_pref_in_list(body, "language", "fr")

    # 3) PUT voice_chat_enabled = true
    put_event_voice = {
        "httpMethod": "PUT",
        "rawPath": "/me/preferences",
        "requestContext": {
            "authorizer": {
                "jwt": {
                    "claims": {
                        "sub": TEST_USER_SUB,
                    }
                }
            }
        },
        "body": json.dumps(
            {"preferenceKey": "voice_chat_enabled", "value": "true"}
        ),
    }
    result = _invoke_lambda(lambda_client, set_fn, put_event_voice)
    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert_pref_in_list(body, "language", "fr")
    assert_pref_in_list(body, "voice_chat_enabled", "true")

    # 4) GET /me/preferences
    get_event = {
        "rawPath": "/me/preferences",
        "requestContext": {
            "authorizer": {
                "jwt": {
                    "claims": {
                        "sub": TEST_USER_SUB,
                    }
                }
            }
        },
    }
    result = _invoke_lambda(lambda_client, get_fn, get_event)
    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert_pref_in_list(body, "language", "fr")
    assert_pref_in_list(body, "voice_chat_enabled", "true")

    # 5) DELETE /me/preferences/language
    delete_event = {
        "httpMethod": "DELETE",
        "rawPath": "/me/preferences/language",
        "pathParameters": {
            "preferenceKey": "language",
        },
        "requestContext": {
            "authorizer": {
                "jwt": {
                    "claims": {
                        "sub": TEST_USER_SUB,
                    }
                }
            }
        },
    }
    result = _invoke_lambda(lambda_client, delete_fn, delete_event)
    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    # language should be gone; voice_chat_enabled remains
    for item in body:
        assert item.get("preferenceKey") != "language"
    assert_pref_in_list(body, "voice_chat_enabled", "true")

