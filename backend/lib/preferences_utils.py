import os
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Optional

from boto3.dynamodb.conditions import Key

import boto3
_table_cache: Dict[str, Any] = {}


def claims_user_id(event: Dict[str, Any]) -> Optional[str]:
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


def get_user(user_id: str) -> Optional[Dict[str, Any]]:
    if not user_id:
        return None
    users_table = _table("USERS_TABLE")
    resp = users_table.get_item(Key={"userId": user_id})
    return resp.get("Item")


def ensure_actor_can_manage_child(actor_id: str, child_id: str) -> Dict[str, Any]:
    actor = get_user(actor_id)
    if not actor:
        raise PermissionError("Actor user record not found")

    role = (actor.get("role") or "").lower()
    if role not in ("adult", "admin"):
        raise PermissionError("Only Adult/Admin can manage children")

    if role == "admin":
        return actor

    child_links_table = _table("CHILD_LINKS_TABLE")
    link_resp = child_links_table.get_item(Key={"adultId": actor_id, "childId": child_id})
    if "Item" not in link_resp:
        raise PermissionError("Child is not linked to this adult")
    return actor


def _parse_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        if isinstance(value, Decimal):
            return int(value)
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_birth_date(birth_date_str: Optional[str]) -> Optional[datetime]:
    if not birth_date_str:
        return None
    try:
        return datetime.strptime(birth_date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _calculate_age(birth_date: Optional[datetime]) -> Optional[int]:
    if not birth_date:
        return None
    today = datetime.now(timezone.utc).date()
    bdate = birth_date.date()
    years = today.year - bdate.year - ((today.month, today.day) < (bdate.month, bdate.day))
    return max(years, 0)


def _fetch_age_threshold(country: Optional[str]) -> Optional[int]:
    if not country:
        country = "DEFAULT"
    age_table = _table("AGE_THRESHOLDS_TABLE")
    response = age_table.get_item(Key={"regionCode": country})
    item = response.get("Item")
    if not item and country != "DEFAULT":
        response = age_table.get_item(Key={"regionCode": "DEFAULT"})
        item = response.get("Item")
    if item and "ageThreshold" in item:
        return _parse_int(item["ageThreshold"])
    return None


def build_user_context(user_id: str) -> Dict[str, Any]:
    user = get_user(user_id) or {}
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


def _normalize_value(value: Any):
    if isinstance(value, Decimal):
        if value % 1 == 0:
            return int(value)
        return float(value)
    return value


def resolve_managed_defaults(user_ctx: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    managed_table = _table("MANAGED_PREFERENCES_TABLE")
    managed_items = _scan_all(managed_table)
    resolved = {}
    for item in managed_items:
        pref_key = item.get("preferenceKey")
        if not pref_key or pref_key in resolved:
            continue
        entry = resolve_single_default(item, user_ctx)
        if entry is not None:
            resolved[pref_key] = entry
    return resolved


def resolve_single_default(schema: Dict[str, Any], user_ctx: Dict[str, Any]) -> Optional[Dict[str, Any]]:
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


def merge_preferences(user_items, defaults, include_defaults: bool):
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


def load_managed_schema(pref_key: str) -> Optional[Dict[str, Any]]:
    managed_table = _table("MANAGED_PREFERENCES_TABLE")
    response = managed_table.query(
        KeyConditionExpression=Key("preferenceKey").eq(pref_key)
    )
    items = response.get("Items", [])
    if not items:
        return None
    # return the most generic scope (or first entry)
    return items[0]


def enforce_preference_restrictions(user_ctx: Dict[str, Any], schema: Dict[str, Any]):
    if not schema:
        return

    if user_ctx.get("is_child"):
        child_override = str(schema.get("childOverride") or "").lower()
        if child_override == "locked":
            raise PermissionError("Preference is locked for children")

    age = user_ctx.get("age")
    min_age = _parse_int(schema.get("minAge"))
    max_age = _parse_int(schema.get("maxAge"))
    if age is not None:
        if min_age is not None and age < min_age:
            raise PermissionError("User is below the minimum age for this preference")
        if max_age is not None and age > max_age:
            raise PermissionError("User exceeds the allowed age for this preference")

