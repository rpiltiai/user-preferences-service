import json
import os
from datetime import datetime

import boto3
from boto3.dynamodb.conditions import Key

dynamodb = boto3.resource("dynamodb")
preferences_table = dynamodb.Table(os.environ["PREFERENCES_TABLE"])
versions_table = dynamodb.Table(os.environ["PREFERENCE_VERSIONS_TABLE"])


def _put_version_entry(user_id, pref_key, old_value, action):
    timestamp = datetime.utcnow().isoformat(timespec="milliseconds") + "Z"
    item = {
        "userId": user_id,
        "preferenceKey_ts": f"{pref_key}#{timestamp}",
        "preferenceKey": pref_key,
        "timestamp": timestamp,
        "action": action,
    }

    if old_value not in (None, ""):
        item["oldValue"] = old_value

    print(
        f"[PreferenceVersions] action={action} userId={user_id} key={pref_key} "
        f"old={old_value}"
    )
    versions_table.put_item(Item=item)


def _claims_user_id(event):
    authorizer = (event.get("requestContext") or {}).get("authorizer") or {}
    jwt_claims = (authorizer.get("jwt") or {}).get("claims") or {}
    legacy_claims = authorizer.get("claims") or {}

    for source in (jwt_claims, legacy_claims):
        if not source:
            continue
        for key in ("sub", "username", "cognito:username"):
            if source.get(key):
                return source[key]
    return None


def _extract_user_id(event):
    # 1) /preferences/{userId}/{preferenceKey}
    path_params = event.get("pathParameters") or {}
    if path_params.get("userId"):
        return path_params["userId"]

    # 2) /me/preferences/{preferenceKey} з Cognito JWT
    return _claims_user_id(event)


def _extract_preference_key(event):
    path_params = event.get("pathParameters") or {}
    return path_params.get("preferenceKey")


def handler(event, context):
    print("Incoming event:", json.dumps(event))

    user_id = _extract_user_id(event)
    pref_key = _extract_preference_key(event)

    if not user_id:
        return {
            "statusCode": 400,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "userId is missing (path or JWT)"}),
        }

    if not pref_key:
        return {
            "statusCode": 400,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "preferenceKey is required in path"}),
        }

    try:
        # Видаляємо один конкретний preference
        existing_item = preferences_table.get_item(
            Key={
                "userId": user_id,
                "preferenceKey": pref_key,
            }
        ).get("Item")

        preferences_table.delete_item(
            Key={
                "userId": user_id,
                "preferenceKey": pref_key,
            }
        )

        old_value = existing_item.get("value") if existing_item else None
        _put_version_entry(
            user_id=user_id,
            pref_key=pref_key,
            old_value=old_value,
            action="DELETE",
        )

        # Читаємо актуальний список prefs користувача після видалення
        response = preferences_table.query(
            KeyConditionExpression=Key("userId").eq(user_id)
        )
        items = response.get("Items", [])

        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(items),
        }

    except Exception as e:
        print("Error:", repr(e))
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": str(e)}),
        }

