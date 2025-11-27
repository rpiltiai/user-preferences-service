import json
import os
import boto3

from boto3.dynamodb.conditions import Key

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(os.environ["PREFERENCES_TABLE"])


def _extract_user_id(event):
    # 1) /preferences/{userId}/{preferenceKey}
    path_params = event.get("pathParameters") or {}
    if "userId" in path_params and path_params["userId"]:
        return path_params["userId"]

    # 2) /me/preferences/{preferenceKey} з Cognito JWT
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
        table.delete_item(
            Key={
                "userId": user_id,
                "preferenceKey": pref_key,
            }
        )

        # Читаємо актуальний список prefs користувача після видалення
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

