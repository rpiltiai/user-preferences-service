import json
import os
from datetime import datetime

import boto3
from boto3.dynamodb.conditions import Key

dynamodb = boto3.resource("dynamodb")
preferences_table = dynamodb.Table(os.environ["PREFERENCES_TABLE"])
versions_table = dynamodb.Table(os.environ["PREFERENCE_VERSIONS_TABLE"])
child_links_table = dynamodb.Table(os.environ["CHILD_LINKS_TABLE"])
users_table = dynamodb.Table(os.environ["USERS_TABLE"])


def _now_iso():
    return datetime.utcnow().isoformat(timespec="milliseconds") + "Z"


def _put_version_entry(user_id, pref_key, old_value, new_value, action):
    """
    Writes an immutable audit record to the PreferenceVersions table.
    Empty strings are skipped because DynamoDB does not accept them.
    """
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

    if new_value not in (None, ""):
        item["newValue"] = new_value

    print(
        f"[PreferenceVersions] action={action} userId={user_id} key={pref_key} "
        f"old={old_value} new={new_value}"
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


def _resolve_target_user(event):
    path_params = event.get("pathParameters") or {}
    child_id = path_params.get("childId")
    path_user_id = path_params.get("userId")
    caller_user_id = _claims_user_id(event)

    if child_id:
        if not caller_user_id:
            raise PermissionError("Authentication (Cognito) is required for child access")
        _ensure_actor_can_manage_child(caller_user_id, child_id)
        return child_id

    if path_user_id:
        return path_user_id

    if caller_user_id:
        return caller_user_id

    raise ValueError("userId is required")


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
        # 1. Determine target user (self, explicit userId, or child)
        try:
            user_id = _resolve_target_user(event)
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

            existing_item = preferences_table.get_item(
                Key={"userId": user_id, "preferenceKey": pref_key}
            ).get("Item")

            stored_value = str(value) if value is not None else ""
            timestamp = _now_iso()

            item = {
                "userId": user_id,
                "preferenceKey": pref_key,
                "value": stored_value,
                "updatedAt": timestamp,
            }

            print("Putting item:", item)
            preferences_table.put_item(Item=item)

            old_value = existing_item.get("value") if existing_item else None
            _put_version_entry(
                user_id=user_id,
                pref_key=pref_key,
                old_value=old_value,
                new_value=stored_value,
                action="UPSERT",
            )

        # 5. Read back all prefs for this user (return current state)
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
