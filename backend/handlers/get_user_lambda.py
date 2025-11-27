import boto3
import json
import os
from decimal import Decimal

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(os.environ["USERS_TABLE"])


def handler(event, context):
    print("Incoming event:", json.dumps(event))

    user_id = event["pathParameters"]["userId"]

    response = table.get_item(Key={"userId": user_id})

    if "Item" not in response:
        return {
            "statusCode": 404,
            "body": json.dumps({"error": "User not found"}),
            "headers": {
                "Content-Type": "application/json"
            },
        }

    item = response["Item"]

    # Простий спосіб: все, що не вміє серіалізуватись, перетворюємо на str
    return {
        "statusCode": 200,
        "body": json.dumps(item, default=str),
        "headers": {
            "Content-Type": "application/json"
        },
    }

