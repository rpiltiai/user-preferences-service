import json
import os

import boto3
from boto3.dynamodb.conditions import Key

from lib.preferences_resolver import (
    build_user_context,
    merge_preferences,
    resolve_managed_defaults,
)

dynamodb = boto3.resource("dynamodb")
preferences_table = dynamodb.Table(os.environ["PREFERENCES_TABLE"])
users_table = dynamodb.Table(os.environ["USERS_TABLE"])
child_links_table = dynamodb.Table(os.environ["CHILD_LINKS_TABLE"])


def handler(event, context):
    print("Incoming event:", json.dumps(event))

    try:
        target_user_id, include_defaults = _resolve_target_user(event)
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
        response = preferences_table.query(
            KeyConditionExpression=Key("userId").eq(target_user_id)
        )
        items = response.get("Items", [])

        defaults = {}
        if include_defaults:
            user_ctx = build_user_context(target_user_id)
            defaults = resolve_managed_defaults(user_ctx)

        merged = merge_preferences(items, defaults, include_defaults=include_defaults)

        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(merged),
        }

    except Exception as exc:
        print("Error:", repr(exc))
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": str(exc)}),
        }


def _resolve_target_user(event):
    path_params = event.get("pathParameters") or {}
    child_id = path_params.get("childId")
    path_user_id = path_params.get("userId")
    caller_user_id = _claims_user_id(event)

    if child_id:
        if not caller_user_id:
            raise PermissionError("Authentication (Cognito) is required for child access")
        _ensure_actor_can_manage_child(caller_user_id, child_id)
        return child_id, True

    if path_user_id:
        return path_user_id, False

    if caller_user_id:
        return caller_user_id, True

    raise ValueError("userId is missing (neither path nor JWT)")


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

