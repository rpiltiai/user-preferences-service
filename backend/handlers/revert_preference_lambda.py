import json
import os
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Key

from lib.preferences_resolver import (
    build_user_context,
    ensure_preference_value_allowed,
    get_managed_preference,
)

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

    caller_user_id = _claims_user_id(event)

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

        schema = get_managed_preference(pref_key)
        user_ctx = build_user_context(user_id)
        try:
            ensure_preference_value_allowed(schema, user_ctx, revert_value)
        except PermissionError as rule_err:
            _log_block(user_id, pref_key, caller_user_id, str(rule_err))
            return {
                "statusCode": 403,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"error": str(rule_err)}),
            }

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


def _log_block(user_id, pref_key, actor_id, reason):
    print(
        "[PreferenceBlocked] "
        f"userId={user_id} actorId={actor_id or 'unknown'} "
        f"preferenceKey={pref_key} reason={reason}"
    )


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

