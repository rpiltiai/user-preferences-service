import base64
import json
import os
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key

dynamodb = boto3.resource("dynamodb")
versions_table = dynamodb.Table(os.environ["PREFERENCE_VERSIONS_TABLE"])


def _decode_next_token(token):
    if not token:
        return None
    try:
        decoded = base64.urlsafe_b64decode(token.encode("utf-8")).decode("utf-8")
        return json.loads(decoded)
    except Exception:
        return None


def _encode_next_token(token):
    if not token:
        return None
    encoded = json.dumps(token).encode("utf-8")
    return base64.urlsafe_b64encode(encoded).decode("utf-8")


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


def handler(event, context):
    print("Incoming event:", json.dumps(event))

    path_params = event.get("pathParameters") or {}
    query_params = event.get("queryStringParameters") or {}

    user_id = path_params.get("userId") or query_params.get("userId")
    if not user_id:
        return {
            "statusCode": 400,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "userId is required"}),
        }

    preference_key = path_params.get("preferenceKey") or query_params.get("preferenceKey")
    limit_raw = query_params.get("limit") or query_params.get("Limit")
    limit = 50
    if limit_raw:
        try:
            limit = max(1, min(200, int(limit_raw)))
        except ValueError:
            pass

    next_token = _decode_next_token(query_params.get("nextToken"))

    key_condition = Key("userId").eq(user_id)
    if preference_key:
        prefix = f"{preference_key}#"
        key_condition = key_condition & Key("preferenceKey_ts").begins_with(prefix)

    query_kwargs = {
        "KeyConditionExpression": key_condition,
        "ScanIndexForward": False,
        "Limit": limit,
    }
    if next_token:
        query_kwargs["ExclusiveStartKey"] = next_token

    try:
        response = versions_table.query(**query_kwargs)
        items = _convert_decimals(response.get("Items", []))

        next_token_out = _encode_next_token(response.get("LastEvaluatedKey"))

        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(
                {
                    "items": items,
                    "nextToken": next_token_out,
                }
            ),
        }
    except Exception as exc:
        print("Error querying PreferenceVersions:", repr(exc))
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "Failed to fetch versions", "details": str(exc)}),
        }

