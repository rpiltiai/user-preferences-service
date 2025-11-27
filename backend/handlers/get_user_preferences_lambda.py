import json
import os
import boto3
from boto3.dynamodb.conditions import Key

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(os.environ["PREFERENCES_TABLE"])


def _extract_user_id(event):
    """
    Повертає userId з:
    1) pathParameters["userId"]  -> для /preferences/{userId}
    2) JWT claims.sub            -> для /me/preferences
    """

    # Варіант 1: /preferences/{userId}
    path_params = event.get("pathParameters") or {}
    if "userId" in path_params and path_params["userId"]:
        return path_params["userId"]

    # Варіант 2: /me/preferences з Cognito JWT
    try:
        claims = (
            event.get("requestContext", {})
            .get("authorizer", {})
            .get("jwt", {})
            .get("claims", {})
        )
        user_id = claims.get("sub") or claims.get("username")
        if user_id:
            return user_id
    except Exception:
        pass

    return None


def handler(event, context):
    print("Incoming event:", json.dumps(event))

    user_id = _extract_user_id(event)
    if not user_id:
        return {
            "statusCode": 400,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "userId is missing (neither path nor JWT)"}),
        }

    try:
        response = table.query(
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

