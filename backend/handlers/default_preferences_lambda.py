import json

from lib.preferences_resolver import (
    build_user_context,
    merge_preferences,
    resolve_managed_defaults,
)


def handler(event, context):
    print("Incoming event:", json.dumps(event))

    query_params = event.get("queryStringParameters") or {}
    requested_user_id = query_params.get("userId")

    actor_user_id = _claims_user_id(event)
    if not requested_user_id:
        requested_user_id = actor_user_id

    if not requested_user_id:
        return {
            "statusCode": 400,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "userId query parameter is required if not authenticated"}),
        }

    try:
        user_ctx = build_user_context(requested_user_id)
        defaults = resolve_managed_defaults(user_ctx)
        merged = merge_preferences([], defaults, include_defaults=True)

        # For consistency, return the same array shape as other endpoints
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(merged),
        }
    except Exception as exc:
        print("Error resolving defaults:", repr(exc))
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "Failed to resolve defaults", "details": str(exc)}),
        }


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

