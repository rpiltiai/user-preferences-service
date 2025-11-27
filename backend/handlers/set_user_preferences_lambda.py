import json
import os

import boto3
from boto3.dynamodb.conditions import Key

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(os.environ["PREFERENCES_TABLE"])


def handler(event, context):
    """
    SET /preferences/{userId}

    Supported invocation patterns:
    1) API Gateway REST: pathParameters["userId"], body = JSON
    2) HTTP API with JWT: userId from requestContext.authorizer.jwt.claims["sub"]
    3) Direct Lambda invoke from CLI/tests with a synthetic event

    Supported body formats:
    1) Single preference object:
       {
         "preferenceKey": "voice_chat_enabled",
         "value": "true"
       }

    2) Array of preference objects:
       [
         {"preferenceKey": "voice_chat_enabled", "value": "true"},
         {"preferenceKey": "language", "value": "en"}
       ]

    3) Map of preference keys:
       {
         "voice_chat_enabled": "true",
         "language": "en"
       }
    """
    print("Incoming event:", json.dumps(event))

    try:
        # 1. Determine userId
        user_id = None

        # Variant 1: REST API with pathParameters (/preferences/{userId})
        path_params = event.get("pathParameters") or {}
        if "userId" in path_params:
            user_id = path_params["userId"]

        # Variant 2: HTTP API / JWT (/me/preferences)
        if not user_id:
            try:
                claims = (
                    event.get("requestContext", {})
                    .get("authorizer", {})
                    .get("jwt", {})
                    .get("claims", {})
                )
                user_id = claims.get("sub")
            except Exception:
                pass

        if not user_id:
            return {
                "statusCode": 400,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"error": "userId is required"}),
            }

        # 2. Parse body
        raw_body = event.get("body") or ""
        if not raw_body:
            return {
                "statusCode": 400,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"error": "Request body is required"}),
            }

        try:
            body = json.loads(raw_body)
        except json.JSONDecodeError:
            return {
                "statusCode": 400,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"error": "Invalid JSON in request body"}),
            }

        # 3. Normalize to list of preferences
        prefs_to_save = []

        if isinstance(body, list):
            # Array of {preferenceKey, value}
            prefs_to_save = body

        elif isinstance(body, dict):
            # Case 3.1: canonical object {"preferenceKey": "...", "value": "..."}
            if "preferenceKey" in body and "value" in body:
                prefs_to_save = [body]
            else:
                # ВАЖЛИВО: якщо є "value", але немає "preferenceKey"
                # і це єдине поле → вважаємо це невалідним
                if "value" in body and "preferenceKey" not in body and len(body) == 1:
                    return {
                        "statusCode": 400,
                        "headers": {"Content-Type": "application/json"},
                        "body": json.dumps(
                            {
                                "error": (
                                    "preferenceKey is required when value is provided"
                                )
                            }
                        ),
                    }

                # Case 3.2: compact map {"voice_chat_enabled": "true", "language": "en"}
                mapped_prefs = []
                for key, value in body.items():
                    # ігноруємо службові ключі, якщо раптом
                    if key in ("preferenceKey", "value"):
                        continue
                    mapped_prefs.append({"preferenceKey": key, "value": value})

                if not mapped_prefs:
                    return {
                        "statusCode": 400,
                        "headers": {"Content-Type": "application/json"},
                        "body": json.dumps(
                            {"error": "Body must contain at least one preference"}
                        ),
                    }

                prefs_to_save = mapped_prefs

        else:
            return {
                "statusCode": 400,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps(
                    {"error": "Body must be an object or array of objects"}
                ),
            }

        if not prefs_to_save:
            return {
                "statusCode": 400,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"error": "No preferences to save"}),
            }

        # 4. Write to DynamoDB (simple upsert)
        for pref in prefs_to_save:
            pref_key = pref.get("preferenceKey")
            value = pref.get("value")

            if not pref_key:
                # Skip invalid entries
                print(f"Skipping preference without key: {pref}")
                continue

            item = {
                "userId": user_id,
                "preferenceKey": pref_key,
                "value": str(value) if value is not None else "",
            }

            print("Putting item:", item)
            table.put_item(Item=item)

        # 5. Read back all prefs for this user (return current state)
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
