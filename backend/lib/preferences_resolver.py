import os
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Iterable

import boto3
from boto3.dynamodb.conditions import Key

dynamodb = boto3.resource("dynamodb")
users_table = dynamodb.Table(os.environ["USERS_TABLE"])
managed_prefs_table = dynamodb.Table(os.environ["MANAGED_PREFERENCES_TABLE"])
age_thresholds_table = dynamodb.Table(os.environ["AGE_THRESHOLDS_TABLE"])


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


def build_user_context(user_id):
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

    normalized = _normalize_value(value)
    return {
        "preferenceKey": schema["preferenceKey"],
        "value": normalized,
        "source": source,
        "resolved": True,
        "isManaged": True,
        "isSet": False,
    }


def resolve_managed_defaults(user_ctx):
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


def merge_preferences(
    user_items: Iterable[Dict[str, Any]],
    defaults: Dict[str, Dict[str, Any]],
    include_defaults: bool,
):
    merged = {}
    managed_keys = set(defaults.keys())

    for item in user_items:
        key = item.get("preferenceKey")
        if not key:
            continue
        enriched = dict(item)
        enriched["source"] = item.get("source") or "user"
        enriched["resolved"] = True
        enriched["isManaged"] = key in managed_keys
        enriched["isSet"] = True
        merged[key] = enriched

    if include_defaults:
        for key, default_entry in defaults.items():
            if key in merged:
                continue
            merged[key] = dict(default_entry)

    return list(merged.values())


def get_managed_preference(pref_key: str) -> Dict[str, Any]:
    if not pref_key:
        return {}
    response = managed_prefs_table.query(
        KeyConditionExpression=Key("preferenceKey").eq(pref_key),
        Limit=1,
    )
    items = response.get("Items", [])
    return items[0] if items else {}


def ensure_preference_value_allowed(schema: Dict[str, Any], user_ctx: Dict[str, Any], desired_value: Any):
    if not schema:
        return

    if desired_value in (None, "", []):
        # Removing an override is always safe
        return

    if not user_ctx.get("is_child"):
        return

    child_override = schema.get("childOverride")
    if isinstance(child_override, str) and child_override.lower() == "locked":
        raise PermissionError("Preference is locked for children")

    age = user_ctx.get("age")
    min_age = _parse_int(schema.get("minAge"))
    max_age = _parse_int(schema.get("maxAge"))

    if min_age is not None and (age is None or age < min_age):
        raise PermissionError("Preference cannot be set below the minimum age")

    if max_age is not None and age is not None and age > max_age:
        raise PermissionError("Preference cannot be set above the maximum age")

