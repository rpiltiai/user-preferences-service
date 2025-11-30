import json
import os
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Key

dynamodb = boto3.resource("dynamodb")
preferences_table = dynamodb.Table(os.environ["PREFERENCES_TABLE"])
versions_table = dynamodb.Table(os.environ["PREFERENCE_VERSIONS_TABLE"])


def _now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _sanitize_value(value):
    if value is None:
        return None
    return str(value)


def _write_version(user_id, pref_key, old_value, new_value, action):
    timestamp = _now_iso()
    item = {
        "userId": user_id,
        "preferenceKey_ts": f"{pref_key}#{timestamp}",
        "preferenceKey": pref_key,
        "timestamp": timestamp,
        "action": action,
    }
    if old_value not in (None, ""):
        item["oldValue"] = old_value
    if new_value not in (None, ""):
        item["newValue"] = new_value
    versions_table.put_item(Item=item)


def handler(event, context):
    print("Incoming event:", json.dumps(event))

    if not event.get("body"):
        return {
            "statusCode": 400,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "Request body is required"}),
        }

    try:
        payload = json.loads(event["body"])
    except json.JSONDecodeError:
        return {
            "statusCode": 400,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "Invalid JSON"}),
        }

    user_id = payload.get("userId")
    pref_key = payload.get("preferenceKey")
    version_key = payload.get("versionKey") or payload.get("preferenceKey_ts")

    if not (user_id and pref_key and version_key):
        return {
            "statusCode": 400,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(
                {
                    "error": "userId, preferenceKey and versionKey are required",
                }
            ),
        }

    try:
        version_resp = versions_table.get_item(
            Key={
                "userId": user_id,
                "preferenceKey_ts": version_key,
            }
        )
        version_item = version_resp.get("Item")
        if not version_item:
            return {
                "statusCode": 404,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"error": "Version not found"}),
            }

        if not version_key.startswith(f"{pref_key}#"):
            return {
                "statusCode": 400,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"error": "versionKey does not match preferenceKey"}),
            }

        revert_value = version_item.get("oldValue")
        current_item = preferences_table.get_item(
            Key={"userId": user_id, "preferenceKey": pref_key}
        ).get("Item")
        current_value = current_item.get("value") if current_item else None

        if revert_value in (None, ""):
            if current_item:
                preferences_table.delete_item(
                    Key={"userId": user_id, "preferenceKey": pref_key}
                )
        else:
            new_item = {
                "userId": user_id,
                "preferenceKey": pref_key,
                "value": _sanitize_value(revert_value),
                "updatedAt": _now_iso(),
            }
            preferences_table.put_item(Item=new_item)

        _write_version(
            user_id=user_id,
            pref_key=pref_key,
            old_value=current_value,
            new_value=revert_value,
            action="REVERT",
        )

        updated = preferences_table.query(
            KeyConditionExpression=Key("userId").eq(user_id)
        ).get("Items", [])

        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(updated),
        }

    except Exception as exc:
        print("Error during revert:", repr(exc))
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "Failed to revert preference", "details": str(exc)}),
        }

