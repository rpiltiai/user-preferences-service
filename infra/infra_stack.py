from aws_cdk import (
    Stack,
    aws_dynamodb as dynamodb,
    aws_lambda as _lambda,
    aws_apigateway as apigw,
)
from constructs import Construct


class InfraStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # -------- DynamoDB tables --------

        # Users table
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

        # Preferences table
        self.preferences_table = dynamodb.Table(
            self,
            "PreferencesTable",
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

        # -------- Lambda: GET /users/{userId} --------

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

        # -------- Lambda: GET /users/{userId}/preferences --------

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

        # Grant read
        self.users_table.grant_read_data(get_user_lambda)
        self.preferences_table.grant_read_data(get_user_preferences_lambda)

        # -------- API Gateway --------

        api = apigw.RestApi(
            self,
            "UserPreferencesApi",
            rest_api_name="UserPreferencesService",
        )

        # /users
        users_resource = api.root.add_resource("users")

        # /users/{userId}
        user_by_id = users_resource.add_resource("{userId}")
        user_by_id.add_method(
            "GET",
            apigw.LambdaIntegration(get_user_lambda),
        )

        # /users/{userId}/preferences
        preferences_resource = user_by_id.add_resource("preferences")
        preferences_resource.add_method(
            "GET",
            apigw.LambdaIntegration(get_user_preferences_lambda),
        )

