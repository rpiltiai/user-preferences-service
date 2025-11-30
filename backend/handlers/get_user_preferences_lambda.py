import json
import os
from datetime import datetime, timezone
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key

dynamodb = boto3.resource("dynamodb")
preferences_table = dynamodb.Table(os.environ["PREFERENCES_TABLE"])
users_table = dynamodb.Table(os.environ["USERS_TABLE"])
managed_prefs_table = dynamodb.Table(os.environ["MANAGED_PREFERENCES_TABLE"])
age_thresholds_table = dynamodb.Table(os.environ["AGE_THRESHOLDS_TABLE"])


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


def _extract_user_id(event):
    """
    Returns userId from either explicit path params (/preferences/{userId}) or Cognito claims (/me/*)
    """

    path_params = event.get("pathParameters") or {}
    if path_params.get("userId"):
        return path_params["userId"]

    return _claims_user_id(event)


def _scan_all(table):
    items = []
    start_key = None
    while True:
        params = {}
        if start_key:
            params["ExclusiveStartKey"] = start_key
        response = table.scan(**params)
        items.extend(response.get("Items", []))
        start_key = response.get("LastEvaluatedKey")
        if not start_key:
            break
    return items


def _normalize_value(value):
    if isinstance(value, Decimal):
        if value % 1 == 0:
            return int(value)
        return float(value)
    return value


def _parse_int(value):
    if value is None:
        return None
    try:
        if isinstance(value, Decimal):
            return int(value)
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_birth_date(birth_date_str):
    if not birth_date_str:
        return None
    try:
        return datetime.strptime(birth_date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _calculate_age(birth_date):
    if not birth_date:
        return None
    today = datetime.now(timezone.utc).date()
    bdate = birth_date.date()
    years = today.year - bdate.year - ((today.month, today.day) < (bdate.month, bdate.day))
    return max(years, 0)


def _fetch_age_threshold(country):
    if not country:
        return None
    response = age_thresholds_table.get_item(Key={"regionCode": country})
    item = response.get("Item")
    if item and "ageThreshold" in item:
        return _parse_int(item["ageThreshold"])
    default_item = age_thresholds_table.get_item(Key={"regionCode": "DEFAULT"}).get("Item")
    if default_item and "ageThreshold" in default_item:
        return _parse_int(default_item["ageThreshold"])
    return None


def _build_user_context(user_id):
    user = users_table.get_item(Key={"userId": user_id}).get("Item") or {}
    birth_date = _parse_birth_date(user.get("birthDate"))
    age = _calculate_age(birth_date)
    country = user.get("country")
    age_threshold = _fetch_age_threshold(country)
    role = (user.get("role") or "").lower()
    is_child = role == "child"
    if not is_child and age is not None and age_threshold is not None:
        is_child = age < age_threshold

    return {
        "user": user,
        "age": age,
        "country": country,
        "is_child": is_child,
    }


def _resolve_single_default(schema, user_ctx):
    value = schema.get("baseDefault")
    source = "baseDefault"

    if user_ctx["is_child"] and schema.get("childOverride") not in (None, ""):
        value = schema["childOverride"]
        source = "childOverride"

    country_overrides = schema.get("countryOverrides") or {}
    user_country = user_ctx["country"]
    if user_country and user_country in country_overrides:
        value = country_overrides[user_country]
        source = "countryOverride"

    age = user_ctx["age"]
    min_age = _parse_int(schema.get("minAge"))
    max_age = _parse_int(schema.get("maxAge"))
    if age is not None:
        if min_age is not None and age < min_age:
            value = None
            source = "ageRestriction"
        if max_age is not None and age > max_age:
            value = None
            source = "ageRestriction"

    if value is None:
        return None

    return {
        "preferenceKey": schema["preferenceKey"],
        "value": _normalize_value(value),
        "source": source,
    }


def _resolve_managed_defaults(user_ctx):
    managed_items = _scan_all(managed_prefs_table)
    resolved = {}
    for item in managed_items:
        pref_key = item.get("preferenceKey")
        if not pref_key or pref_key in resolved:
            continue
        resolved_entry = _resolve_single_default(item, user_ctx)
        if resolved_entry is not None:
            resolved[pref_key] = resolved_entry
    return resolved


def _merge_preferences(user_items, defaults, include_defaults):
    merged = {}
    for item in user_items:
        key = item.get("preferenceKey")
        if not key:
            continue
        enriched = dict(item)
        enriched["source"] = "user"
        enriched["resolved"] = True
        merged[key] = enriched

    if include_defaults:
        for key, default_entry in defaults.items():
            if key in merged:
                continue
            merged[key] = {
                "preferenceKey": key,
                "value": default_entry["value"],
                "source": default_entry["source"],
                "resolved": True,
            }
    return list(merged.values())


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
        response = preferences_table.query(
            KeyConditionExpression=Key("userId").eq(user_id)
        )
        items = response.get("Items", [])

        path_params = event.get("pathParameters") or {}
        include_defaults = not path_params.get("userId")

        if include_defaults:
            user_ctx = _build_user_context(user_id)
            defaults = _resolve_managed_defaults(user_ctx)
            items = _merge_preferences(items, defaults, include_defaults=True)
        else:
            items = _merge_preferences(items, {}, include_defaults=False)

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

