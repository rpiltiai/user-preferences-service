# User Preferences Management System

Mono-repo for AWS-based user preferences service (MSE Capstone).

Structure:
- infra/   – AWS CDK infrastructure (DynamoDB, Lambdas, APIs, Cognito, etc.)
- backend/ – Lambda handlers and core business logic
- portal/  – React/Vite dev portal for Cognito auth + API smoke-tests (`portal/README.md`)
- game1/   – Demo game client using REST API
- game2/   – Demo game client using GraphQL API
