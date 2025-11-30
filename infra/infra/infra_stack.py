from aws_cdk import (
    Stack,
    CfnOutput,
    aws_lambda as _lambda,
    aws_apigateway as apigw,
    aws_dynamodb as dynamodb,
)
from constructs import Construct


class InfraStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        #
        # 1. DynamoDB tables
        #

        # Основна таблиця з вподобаннями (як було раніше)
        self.preferences_table = dynamodb.Table(
            self,
            "UserPreferencesTable",
            table_name="Preferences",
            partition_key=dynamodb.Attribute(
                name="userId",
                type=dynamodb.AttributeType.STRING,
            ),
            sort_key=dynamodb.Attribute(
                name="preferenceKey",
                type=dynamodb.AttributeType.STRING,
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
        )

        # Таблиця користувачів (Adult / Child / Admin)
        self.users_table = dynamodb.Table(
            self,
            "UsersTable",
            table_name="Users",
            partition_key=dynamodb.Attribute(
                name="userId",
                type=dynamodb.AttributeType.STRING,
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
        )

        # Схема керованих вподобань
        self.managed_prefs_table = dynamodb.Table(
            self,
            "ManagedPreferenceSchemaTable",
            table_name="ManagedPreferenceSchema",
            partition_key=dynamodb.Attribute(
                name="preferenceKey",
                type=dynamodb.AttributeType.STRING,
            ),
            sort_key=dynamodb.Attribute(
                name="scope",
                type=dynamodb.AttributeType.STRING,
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
        )

        # Історія змін вподобань (версії)
        self.preference_versions_table = dynamodb.Table(
            self,
            "PreferenceVersionsTable",
            table_name="PreferenceVersions",
            partition_key=dynamodb.Attribute(
                name="userId",
                type=dynamodb.AttributeType.STRING,
            ),
            sort_key=dynamodb.Attribute(
                name="preferenceKey_ts",  # key+timestamp
                type=dynamodb.AttributeType.STRING,
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
        )

        # Зв’язки дорослий ↔ дитина
        self.child_links_table = dynamodb.Table(
            self,
            "ChildLinksTable",
            table_name="ChildLinks",
            partition_key=dynamodb.Attribute(
                name="adultId",
                type=dynamodb.AttributeType.STRING,
            ),
            sort_key=dynamodb.Attribute(
                name="childId",
                type=dynamodb.AttributeType.STRING,
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
        )

        # Вікові пороги за регіонами
        self.age_thresholds_table = dynamodb.Table(
            self,
            "AgeThresholdsTable",
            table_name="AgeThresholds",
            partition_key=dynamodb.Attribute(
                name="regionCode",  # "UA", "EU", "US"
                type=dynamodb.AttributeType.STRING,
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
        )

        #
        # 2. Lambda-функції
        #

        # 2.1. GET preferences (GET /preferences/{userId}, /me/preferences)
        get_user_preferences_lambda = _lambda.Function(
            self,
            "GetUserPreferencesFunction",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="handlers.get_user_preferences_lambda.handler",
            code=_lambda.Code.from_asset("../backend"),
            environment={
                "PREFERENCES_TABLE": self.preferences_table.table_name,
            },
        )

        # 2.2. SET preferences (PUT /preferences/{userId}, /me/preferences)
        #      ➜ тепер ще й пише в таблицю версій
        set_user_preferences_lambda = _lambda.Function(
            self,
            "SetUserPreferencesFunction",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="handlers.set_user_preferences_lambda.handler",
            code=_lambda.Code.from_asset("../backend"),
            environment={
                "PREFERENCES_TABLE": self.preferences_table.table_name,
                "PREFERENCE_VERSIONS_TABLE": self.preference_versions_table.table_name,
            },
        )

        # 2.3. DELETE preference (DELETE /preferences/{userId}/{preferenceKey}, /me/preferences/{preferenceKey})
        delete_user_preference_lambda = _lambda.Function(
            self,
            "DeleteUserPreferenceFunction",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="handlers.delete_user_preference_lambda.handler",
            code=_lambda.Code.from_asset("../backend"),
            environment={
                "PREFERENCES_TABLE": self.preferences_table.table_name,
            },
        )

        # 2.4. GET user (GET /users/{userId}) – простий приклад, читає із таблиці Users
        get_user_lambda = _lambda.Function(
            self,
            "GetUserFunction",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="handlers.get_user_lambda.handler",
            code=_lambda.Code.from_asset("../backend"),
            environment={
                "USERS_TABLE": self.users_table.table_name,
            },
        )

        #
        # 3. Доступ до DynamoDB
        #

        self.preferences_table.grant_read_data(get_user_preferences_lambda)
        self.preferences_table.grant_read_write_data(set_user_preferences_lambda)
        self.preferences_table.grant_read_data(delete_user_preference_lambda)

        # get_user читає з таблиці Users
        self.users_table.grant_read_data(get_user_lambda)

        # версіонування: set_user_preferences може писати в таблицю версій
        self.preference_versions_table.grant_write_data(set_user_preferences_lambda)

        #
        # 4. API Gateway
        #

        api = apigw.RestApi(
            self,
            "UserPreferencesApi",
            rest_api_name="UserPreferences Service",
        )

        # /users/{userId} -> GET
        users = api.root.add_resource("users")
        user_id = users.add_resource("{userId}")
        user_id.add_method(
            "GET",
            apigw.LambdaIntegration(get_user_lambda),
        )

        # /preferences/{userId} -> GET, PUT
        pref_users = api.root.add_resource("preferences")
        pref_user_id = pref_users.add_resource("{userId}")
        pref_user_id.add_method(
            "GET",
            apigw.LambdaIntegration(get_user_preferences_lambda),
        )
        pref_user_id.add_method(
            "PUT",
            apigw.LambdaIntegration(set_user_preferences_lambda),
        )

        # /preferences/{userId}/{preferenceKey} -> DELETE
        pref_user_pref_key = pref_user_id.add_resource("{preferenceKey}")
        pref_user_pref_key.add_method(
            "DELETE",
            apigw.LambdaIntegration(delete_user_preference_lambda),
        )

        # /me/preferences -> GET, PUT
        me = api.root.add_resource("me")
        me_preferences = me.add_resource("preferences")
        me_preferences.add_method(
            "GET",
            apigw.LambdaIntegration(get_user_preferences_lambda),
        )
        me_preferences.add_method(
            "PUT",
            apigw.LambdaIntegration(set_user_preferences_lambda),
        )

        # /me/preferences/{preferenceKey} -> DELETE
        me_pref_key = me_preferences.add_resource("{preferenceKey}")
        me_pref_key.add_method(
            "DELETE",
            apigw.LambdaIntegration(delete_user_preference_lambda),
        )

        #
        # 5. Output API URL
        #
        CfnOutput(
            self,
            "UserPreferencesApiEndpoint",
            value=api.url,
        )

