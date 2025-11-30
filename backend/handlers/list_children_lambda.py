import json
import os
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key

dynamodb = boto3.resource("dynamodb")
child_links_table = dynamodb.Table(os.environ["CHILD_LINKS_TABLE"])
users_table = dynamodb.Table(os.environ["USERS_TABLE"])


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


def _convert_decimals(obj):
    if isinstance(obj, list):
        return [_convert_decimals(i) for i in obj]
    if isinstance(obj, dict):
        return {k: _convert_decimals(v) for k, v in obj.items()}
    if isinstance(obj, Decimal):
        if obj % 1 == 0:
            return int(obj)
        return float(obj)
    return obj


def _get_user(user_id):
    if not user_id:
        return None
    resp = users_table.get_item(Key={"userId": user_id})
    return resp.get("Item")


def _ensure_actor_is_adult(actor_id):
    actor = _get_user(actor_id)
    if not actor:
        raise PermissionError("User record not found")
    role = (actor.get("role") or "").lower()
    if role not in ("adult", "admin"):
        raise PermissionError("Only Adult/Admin can list children")
    return actor


def _batch_get_users(user_ids):
    if not user_ids:
        return {}
    keys = [{"userId": child_id} for child_id in user_ids]
    client = dynamodb.meta.client
    response = client.batch_get_item(
        RequestItems={
            users_table.name: {
                "Keys": keys,
            },
        }
    )
    results = response.get("Responses", {}).get(users_table.name, [])
    return {item["userId"]: item for item in results}


def handler(event, context):
    print("Incoming event:", json.dumps(event))

    actor_id = _claims_user_id(event)
    if not actor_id:
        return {
            "statusCode": 401,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "Authentication required"}),
        }

    try:
        _ensure_actor_is_adult(actor_id)
    except PermissionError as err:
        return {
            "statusCode": 403,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": str(err)}),
        }

    try:
        response = child_links_table.query(
            KeyConditionExpression=Key("adultId").eq(actor_id)
        )
        links = response.get("Items", [])
        child_ids = [item.get("childId") for item in links if item.get("childId")]
        child_profiles = _batch_get_users(child_ids)

        result = []
        for link in links:
            child_id = link.get("childId")
            profile = child_profiles.get(child_id) or {}
            entry = {
                "childId": child_id,
                "link": _convert_decimals(link),
                "profile": _convert_decimals(profile),
            }
            result.append(entry)

        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(result),
        }
    except Exception as exc:
        print("Error listing children:", repr(exc))
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "Failed to list children", "details": str(exc)}),
        }

