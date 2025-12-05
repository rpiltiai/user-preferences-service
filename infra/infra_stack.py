from aws_cdk import (
    Stack,
    aws_cognito as cognito,
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





	    # ManagedPreferenceSchema table – схема керованих вподобань
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

    # PreferenceVersions table – історія змін вподобань
    self.preference_versions_table = dynamodb.Table(
        self,
        "PreferenceVersionsTable",
        table_name="PreferenceVersions",
        partition_key=dynamodb.Attribute(
            name="userId",
            type=dynamodb.AttributeType.STRING,
        ),
        sort_key=dynamodb.Attribute(
            name="preferenceKey_ts",   # key#timestamp
            type=dynamodb.AttributeType.STRING,
        ),
        billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
    )

    # ChildLinks table – зв’язки дорослий ↔ дитина
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

    # AgeThresholds table – вікові пороги по регіонах
    self.age_thresholds_table = dynamodb.Table(
        self,
        "AgeThresholdsTable",
        table_name="AgeThresholds",
        partition_key=dynamodb.Attribute(
            name="regionCode",   # UA, EU, US
            type=dynamodb.AttributeType.STRING,
        ),
        billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
    )





        # -------- Cognito (User Pool for /me authorizer) --------

        user_pool = cognito.UserPool(
            self,
            "PreferencesUserPool",
            self_sign_up_enabled=False,
            sign_in_aliases=cognito.SignInAliases(email=True, username=True),
        )

        user_pool_client = user_pool.add_client(
            "PreferencesUserPoolClient",
            auth_flows=cognito.AuthFlow(
                admin_user_password=True,
                user_password=True,
                user_srp=True,
            ),
        )
        self.user_pool = user_pool
        self.user_pool_client = user_pool_client

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
                "USERS_TABLE": self.users_table.table_name,
                "MANAGED_PREFERENCES_TABLE": self.managed_prefs_table.table_name,
                "AGE_THRESHOLDS_TABLE": self.age_thresholds_table.table_name,
                "CHILD_LINKS_TABLE": self.child_links_table.table_name,
            },
        )

        # -------- Lambda: GET /default-preferences --------

        default_preferences_lambda = _lambda.Function(
            self,
            "DefaultPreferencesFunction",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="handlers.default_preferences_lambda.handler",
            code=_lambda.Code.from_asset("../backend"),
            environment={
                "USERS_TABLE": self.users_table.table_name,
                "MANAGED_PREFERENCES_TABLE": self.managed_prefs_table.table_name,
                "AGE_THRESHOLDS_TABLE": self.age_thresholds_table.table_name,
            },
        )

        # -------- Lambda: PUT /preferences/{userId}, /me/preferences --------

        set_user_preferences_lambda = _lambda.Function(
            self,
            "SetUserPreferencesFunction",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="handlers.set_user_preferences_lambda.handler",
            code=_lambda.Code.from_asset("../backend"),
            environment={
                "PREFERENCES_TABLE": self.preferences_table.table_name,
                "PREFERENCE_VERSIONS_TABLE": self.preference_versions_table.table_name,
                "CHILD_LINKS_TABLE": self.child_links_table.table_name,
                "USERS_TABLE": self.users_table.table_name,
                "MANAGED_PREFERENCES_TABLE": self.managed_prefs_table.table_name,
                "AGE_THRESHOLDS_TABLE": self.age_thresholds_table.table_name,
            },
        )

        # -------- Lambda: DELETE /preferences/{userId}/{preferenceKey}, /me/preferences/{preferenceKey} --------

        delete_user_preference_lambda = _lambda.Function(
            self,
            "DeleteUserPreferenceFunction",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="handlers.delete_user_preference_lambda.handler",
            code=_lambda.Code.from_asset("../backend"),
            environment={
                "PREFERENCES_TABLE": self.preferences_table.table_name,
                "PREFERENCE_VERSIONS_TABLE": self.preference_versions_table.table_name,
                "CHILD_LINKS_TABLE": self.child_links_table.table_name,
                "USERS_TABLE": self.users_table.table_name,
                "MANAGED_PREFERENCES_TABLE": self.managed_prefs_table.table_name,
                "AGE_THRESHOLDS_TABLE": self.age_thresholds_table.table_name,
            },
        )

        # -------- Lambda: GET /preference-versions* --------

        list_preference_versions_lambda = _lambda.Function(
            self,
            "ListPreferenceVersionsFunction",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="handlers.list_preference_versions_lambda.handler",
            code=_lambda.Code.from_asset("../backend"),
            environment={
                "PREFERENCE_VERSIONS_TABLE": self.preference_versions_table.table_name,
            },
        )

        # -------- Lambda: POST /preferences/revert --------
        # -------- Lambda: GET /children --------

        list_children_lambda = _lambda.Function(
            self,
            "ListChildrenFunction",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="handlers.list_children_lambda.handler",
            code=_lambda.Code.from_asset("../backend"),
            environment={
                "CHILD_LINKS_TABLE": self.child_links_table.table_name,
                "USERS_TABLE": self.users_table.table_name,
            },
        )

        revert_preference_lambda = _lambda.Function(
            self,
            "RevertPreferenceFunction",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="handlers.revert_preference_lambda.handler",
            code=_lambda.Code.from_asset("../backend"),
            environment={
                "PREFERENCES_TABLE": self.preferences_table.table_name,
                "PREFERENCE_VERSIONS_TABLE": self.preference_versions_table.table_name,
                "MANAGED_PREFERENCES_TABLE": self.managed_prefs_table.table_name,
                "USERS_TABLE": self.users_table.table_name,
                "AGE_THRESHOLDS_TABLE": self.age_thresholds_table.table_name,
            },
        )

        # Grant read
        self.users_table.grant_read_data(get_user_lambda)
        self.users_table.grant_read_data(get_user_preferences_lambda)
        self.users_table.grant_read_data(set_user_preferences_lambda)
        self.users_table.grant_read_data(delete_user_preference_lambda)
        self.users_table.grant_read_data(revert_preference_lambda)
        self.users_table.grant_read_data(default_preferences_lambda)
        self.preferences_table.grant_read_data(get_user_preferences_lambda)
        self.preferences_table.grant_read_write_data(set_user_preferences_lambda)
        self.preferences_table.grant_read_write_data(delete_user_preference_lambda)
        self.managed_prefs_table.grant_read_data(get_user_preferences_lambda)
        self.managed_prefs_table.grant_read_data(default_preferences_lambda)
        self.managed_prefs_table.grant_read_data(set_user_preferences_lambda)
        self.managed_prefs_table.grant_read_data(delete_user_preference_lambda)
        self.managed_prefs_table.grant_read_data(revert_preference_lambda)
        self.age_thresholds_table.grant_read_data(get_user_preferences_lambda)
        self.age_thresholds_table.grant_read_data(default_preferences_lambda)
        self.age_thresholds_table.grant_read_data(set_user_preferences_lambda)
        self.age_thresholds_table.grant_read_data(delete_user_preference_lambda)
        self.age_thresholds_table.grant_read_data(revert_preference_lambda)
        self.child_links_table.grant_read_data(get_user_preferences_lambda)
        self.child_links_table.grant_read_data(set_user_preferences_lambda)
        self.child_links_table.grant_read_data(delete_user_preference_lambda)
        self.child_links_table.grant_read_data(list_children_lambda)
        self.users_table.grant_read_data(list_children_lambda)
        self.preference_versions_table.grant_write_data(set_user_preferences_lambda)
        self.preference_versions_table.grant_write_data(delete_user_preference_lambda)
        self.preference_versions_table.grant_read_data(list_preference_versions_lambda)
        self.preference_versions_table.grant_read_write_data(revert_preference_lambda)
        self.preferences_table.grant_read_write_data(revert_preference_lambda)

        # -------- API Gateway --------

        api = apigw.RestApi(
            self,
            "UserPreferencesApi",
            rest_api_name="UserPreferencesService",
        )

        me_authorizer = apigw.CognitoUserPoolsAuthorizer(
            self,
            "MeAuthorizer",
            cognito_user_pools=[user_pool],
            authorizer_name="UserPreferencesMeAuthorizer",
        )
        me_authorizer._attach_to_api(api)

        # /users
        users_resource = api.root.add_resource("users")

        # /users/{userId}
        user_by_id = users_resource.add_resource("{userId}")
        user_by_id.add_method(
            "GET",
            apigw.LambdaIntegration(get_user_lambda),
        )

        # /users/{userId}/preferences
        user_preferences_resource = user_by_id.add_resource("preferences")
        user_preferences_resource.add_method(
            "GET",
            apigw.LambdaIntegration(get_user_preferences_lambda),
        )

        # /preferences/{userId} (public API used by tests & game clients)
        preferences_root = api.root.add_resource("preferences")
        preferences_by_user = preferences_root.add_resource("{userId}")
        preferences_by_user.add_method(
            "GET",
            apigw.LambdaIntegration(get_user_preferences_lambda),
        )
        preferences_by_user.add_method(
            "PUT",
            apigw.LambdaIntegration(set_user_preferences_lambda),
        )

        # /preferences/{userId}/{preferenceKey}
        preference_item = preferences_by_user.add_resource("{preferenceKey}")
        preference_item.add_method(
            "DELETE",
            apigw.LambdaIntegration(delete_user_preference_lambda),
        )

        # /preferences/revert
        preferences_revert = preferences_root.add_resource("revert")
        preferences_revert.add_method(
            "POST",
            apigw.LambdaIntegration(revert_preference_lambda),
        )

        # /me/preferences (JWT-protected path, Lambda expects Cognito claims)
        me_resource = api.root.add_resource(
            "me",
            default_method_options=apigw.MethodOptions(
                authorization_type=apigw.AuthorizationType.COGNITO,
                authorizer=me_authorizer,
            ),
        )
        me_preferences = me_resource.add_resource("preferences")
        me_preferences.add_method(
            "GET",
            apigw.LambdaIntegration(get_user_preferences_lambda),
        )
        me_preferences.add_method(
            "PUT",
            apigw.LambdaIntegration(set_user_preferences_lambda),
        )

        me_preference_key = me_preferences.add_resource("{preferenceKey}")
        me_preference_key.add_method(
            "DELETE",
            apigw.LambdaIntegration(delete_user_preference_lambda),
        )

        # /children (Adult/Admin only via Cognito)
        children_resource = api.root.add_resource(
            "children",
            default_method_options=apigw.MethodOptions(
                authorization_type=apigw.AuthorizationType.COGNITO,
                authorizer=me_authorizer,
            ),
        )
        children_resource.add_method(
            "GET",
            apigw.LambdaIntegration(list_children_lambda),
        )

        child_by_id = children_resource.add_resource("{childId}")
        child_preferences = child_by_id.add_resource("preferences")
        child_preferences.add_method(
            "GET",
            apigw.LambdaIntegration(get_user_preferences_lambda),
        )
        child_preferences.add_method(
            "PUT",
            apigw.LambdaIntegration(set_user_preferences_lambda),
        )
        child_preference_key = child_preferences.add_resource("{preferenceKey}")
        child_preference_key.add_method(
            "DELETE",
            apigw.LambdaIntegration(delete_user_preference_lambda),
        )

        # /preference-versions
        preference_versions_root = api.root.add_resource("preference-versions")
        preference_versions_root.add_method(
            "GET",
            apigw.LambdaIntegration(list_preference_versions_lambda),
        )

        preference_versions_by_user = preference_versions_root.add_resource("{userId}")
        preference_versions_by_user.add_method(
            "GET",
            apigw.LambdaIntegration(list_preference_versions_lambda),
        )

        preference_versions_by_key = preference_versions_by_user.add_resource("{preferenceKey}")
        preference_versions_by_key.add_method(
            "GET",
            apigw.LambdaIntegration(list_preference_versions_lambda),
        )

        # /default-preferences
        default_preferences = api.root.add_resource("default-preferences")
        default_preferences.add_method(
            "GET",
            apigw.LambdaIntegration(default_preferences_lambda),
        )

