import json
import os
from datetime import datetime

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
users_table = dynamodb.Table(os.environ["USERS_TABLE"])
child_links_table = dynamodb.Table(os.environ["CHILD_LINKS_TABLE"])


def _now_iso():
    return datetime.utcnow().isoformat(timespec="milliseconds") + "Z"


def _put_version_entry(user_id, pref_key, old_value):
    timestamp = _now_iso()
    item = {
        "userId": user_id,
        "preferenceKey_ts": f"{pref_key}#{timestamp}",
        "preferenceKey": pref_key,
        "timestamp": timestamp,
        "action": "DELETE",
    }

    if old_value not in (None, ""):
        item["oldValue"] = old_value

    print(
        f"[PreferenceVersions] action=DELETE userId={user_id} key={pref_key} "
        f"old={old_value}"
    )
    versions_table.put_item(Item=item)


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


def _get_user(user_id):
    if not user_id:
        return None
    resp = users_table.get_item(Key={"userId": user_id})
    return resp.get("Item")


def _ensure_actor_can_manage_child(actor_id, child_id):
    actor = _get_user(actor_id)
    if not actor:
        raise PermissionError("Actor user record not found")
    role = (actor.get("role") or "").lower()
    if role not in ("adult", "admin"):
        raise PermissionError("Only Adult/Admin can manage children")
    if role == "admin":
        return actor
    link_resp = child_links_table.get_item(
        Key={"adultId": actor_id, "childId": child_id}
    )
    if "Item" not in link_resp:
        raise PermissionError("Child is not linked to this adult")
    return actor


def _resolve_target_user(event, caller_user_id):
    path_params = event.get("pathParameters") or {}
    child_id = path_params.get("childId")
    path_user_id = path_params.get("userId")

    if child_id:
        if not caller_user_id:
            raise PermissionError("Authentication (Cognito) is required for child access")
        _ensure_actor_can_manage_child(caller_user_id, child_id)
        return child_id

    if path_user_id:
        return path_user_id

    if caller_user_id:
        return caller_user_id

    raise ValueError("userId is missing (path parameter or JWT)")


def handler(event, context):
    print("Incoming event:", json.dumps(event))

    caller_user_id = _claims_user_id(event)
    path_params = event.get("pathParameters") or {}
    pref_key = path_params.get("preferenceKey")

    if not pref_key:
        return {
            "statusCode": 400,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "preferenceKey is required in path"}),
        }

    try:
        user_id = _resolve_target_user(event, caller_user_id)
    except PermissionError as auth_err:
        return {
            "statusCode": 403,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": str(auth_err)}),
        }
    except ValueError as ve:
        return {
            "statusCode": 400,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": str(ve)}),
        }

    try:
        existing_item = preferences_table.get_item(
            Key={
                "userId": user_id,
                "preferenceKey": pref_key,
            }
        ).get("Item")

        schema = get_managed_preference(pref_key)
        user_ctx = build_user_context(user_id)
        try:
            ensure_preference_value_allowed(schema, user_ctx, None)
        except PermissionError as rule_err:
            _log_block(user_id, pref_key, caller_user_id, str(rule_err))
            return {
                "statusCode": 403,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"error": str(rule_err)}),
            }

        preferences_table.delete_item(
            Key={
                "userId": user_id,
                "preferenceKey": pref_key,
            }
        )

        old_value = existing_item.get("value") if existing_item else None
        _put_version_entry(user_id, pref_key, old_value)

        response = preferences_table.query(
            KeyConditionExpression=Key("userId").eq(user_id)
        )
        items = response.get("Items", [])

        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(items),
        }

    except PermissionError as rule_err:
        _log_block(user_id, pref_key, caller_user_id, str(rule_err))
        return {
            "statusCode": 403,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": str(rule_err)}),
        }
    except Exception as e:
        print("Error:", repr(e))
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": str(e)}),
        }

