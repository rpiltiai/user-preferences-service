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
        # 1. DynamoDB table for user preferences
        #
        self.preferences_table = dynamodb.Table(
            self,
            "UserPreferencesTable",
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

        #
        # 2. Lambda: getUserPreferences (GET /preferences/{userId}, /me/preferences)
        #
        get_user_preferences_lambda = _lambda.Function(
            self,
            "GetUserPreferencesFunction",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="handlers/get_user_preferences_lambda.handler",
            code=_lambda.Code.from_asset("../backend"),
            environment={
                "PREFERENCES_TABLE": self.preferences_table.table_name,
            },
        )

        #
        # 3. Lambda: setUserPreferences (PUT /preferences/{userId}, /me/preferences)
        #
        set_user_preferences_lambda = _lambda.Function(
            self,
            "SetUserPreferencesFunction",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="handlers/set_user_preferences_lambda.handler",
            code=_lambda.Code.from_asset("../backend"),
            environment={
                "PREFERENCES_TABLE": self.preferences_table.table_name,
            },
        )

        #
        # 4. Lambda: deleteUserPreference (DELETE /preferences/{userId}/{preferenceKey},
        #                                 /me/preferences/{preferenceKey})
        #
        delete_user_preference_lambda = _lambda.Function(
            self,
            "DeleteUserPreferenceFunction",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="handlers/delete_user_preference_lambda.handler",
            code=_lambda.Code.from_asset("../backend"),
            environment={
                "PREFERENCES_TABLE": self.preferences_table.table_name,
            },
        )

        #
        # 5. Lambda: getUser (GET /users/{userId}) – простий приклад
        #
        get_user_lambda = _lambda.Function(
            self,
            "GetUserFunction",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="handlers/get_user_lambda.handler",
            code=_lambda.Code.from_asset("../backend"),
            environment={
                # для простоти використовуємо ту саму таблицю
                "USERS_TABLE": self.preferences_table.table_name,
            },
        )

        #
        # 6. DynamoDB permissions
        #
        self.preferences_table.grant_read_data(get_user_preferences_lambda)
        self.preferences_table.grant_read_write_data(set_user_preferences_lambda)
        self.preferences_table.grant_read_write_data(delete_user_preference_lambda)
        self.preferences_table.grant_read_data(get_user_lambda)

        #
        # 7. API Gateway
        #
        api = apigw.RestApi(
            self,
            "UserPreferencesApi",
            rest_api_name="UserPreferences Service",
        )

        #
        # /users/{userId} -> GET
        #
        users = api.root.add_resource("users")
        user_id = users.add_resource("{userId}")
        user_id.add_method(
            "GET",
            apigw.LambdaIntegration(get_user_lambda),
        )

        #
        # /preferences/{userId} -> GET, PUT
        #
        preferences = api.root.add_resource("preferences")
        pref_user_id = preferences.add_resource("{userId}")
        pref_user_id.add_method(
            "GET",
            apigw.LambdaIntegration(get_user_preferences_lambda),
        )
        pref_user_id.add_method(
            "PUT",
            apigw.LambdaIntegration(set_user_preferences_lambda),
        )

        #
        # /preferences/{userId}/{preferenceKey} -> DELETE
        #
        pref_user_pref_key = pref_user_id.add_resource("{preferenceKey}")
        pref_user_pref_key.add_method(
            "DELETE",
            apigw.LambdaIntegration(delete_user_preference_lambda),
        )

        #
        # /me/preferences -> GET, PUT
        #
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

        #
        # /me/preferences/{preferenceKey} -> DELETE
        #
        me_pref_key = me_preferences.add_resource("{preferenceKey}")
        me_pref_key.add_method(
            "DELETE",
            apigw.LambdaIntegration(delete_user_preference_lambda),
        )

        #
        # 8. Output API URL
        #
        CfnOutput(
            self,
            "UserPreferencesApiEndpoint",
            value=api.url,
        )


