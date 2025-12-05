1. Overview of the System

The User Preferences Management System is a backend-centric platform for:

зберігання користувацьких налаштувань (preferences),

parental control: Adult ↔ Child,

default preferences resolution,

audit and versioning,

підтримка двох типів клієнтів гри:

Game Client 1 (REST API)

Game Client 2 (GraphQL API),

Web Portal (Adult/Child interface),

Admin Dashboard (read-only),

import/export preferences,

AI-based heuristic recommendations.

Система орієнтована на використання в ігровій екосистемі, де:

кілька ігор можуть працювати з одними й тими ж налаштуваннями,

дії в одній грі синхронно впливають на інші,

дитині може бути заборонено змінювати деякі налаштування,

дефолтні значення залежать від країни/віку.

1.1 Current implementation snapshot (Nov 2025)

- Репозиторій містить лише `backend/handlers` (Lambda-код), `infra/` (CDK стек, що посилається на `infra/infra_stack.py`) та `tests/`. Каталоги, згадані в README (`portal/`, `game1/`, `game2/`), ще не створені.
- Поточний стек (`infra/infra_stack.py`) створює API Gateway з маршрутами `/users/{userId}`, `/users/{userId}/preferences`, `/preferences/{userId}` (GET/PUT) та `/preferences/{userId}/{preferenceKey}` (DELETE), Lambda-функції `get_user_lambda.py`, `get_user_preferences_lambda.py`, `set_user_preferences_lambda.py`, `delete_user_preference_lambda.py`, а також шість DynamoDB-таблиць (`Users`, `Preferences`, `ManagedPreferenceSchema`, `PreferenceVersions`, `ChildLinks`, `AgeThresholds`).
- `/me/preferences` та `/me/preferences/{preferenceKey}` маршрути захищені Cognito authorizer, Lambda витягує userId з JWT та застосовує default resolver перед тим, як повернути відповідь.
- Cognito, AppSync, S3-портали, EventBridge та CI/CD не створені; авторизація обмежується читанням JWT claims, якщо вони вже передані в події.
- У `tests/` є чотири інтеграційні тести (`test_public_preferences_api.py`, `test_me_lambdas.py`), які очікують, що користувач вручну передасть API base URL та назви Lambda-функцій через змінні середовища.

2. Architecture
2.1 Current AWS Components (deployed via infra/infra_stack.py)

- API Gateway (REST) з GET-маршрутами `/users/{userId}` та `/users/{userId}/preferences`.
- AWS Lambda: `get_user_lambda` (читає таблицю `Users`) і `get_user_preferences_lambda` (читає `Preferences`, підтримує `/preferences/{userId}` та `/me`-семантику при прямому виклику).
- DynamoDB: створені таблиці `Users`, `Preferences`, `ManagedPreferenceSchema`, `PreferenceVersions`, `ChildLinks`, `AgeThresholds` (останні чотири поки що не використовуються бізнес-логікою).

2.2 AWS Components (Target, згідно Capstone)

- API Gateway (REST)
- AWS AppSync (GraphQL)
- AWS Lambda (business logic)
- DynamoDB (6 tables)
- Cognito User Pools (Adult/Child/Admin roles)
- S3 (import/export storage + portals static hosting)
- EventBridge (audit events)
- CloudWatch dashboards & logs
- CI/CD pipeline (GitHub Actions)

3. Target Data Model (DynamoDB)
3.1 Table: Users

Stores user profiles.

Status: таблиця вже створена CDK та використовується лише `backend/handlers/get_user_lambda.py`; дані потрібно додавати вручну.

Field	Type	Notes
userId	PK	UUID
role	String	Adult, Child, Admin
country	String	ISO country
birthDate	String	YYYY-MM-DD
email	String	optional
3.2 Table: Preferences

Stores current effective preferences.

Status: таблиця активно використовується всіма preference-хендлерами; `/me/*` відповіді також проганяються через default resolver, який комбінує ManagedPreferenceSchema + AgeThresholds.

Field	Type	Notes
userId	PK	
preferenceKey	SK	
value	String/Number/Bool	stored value
updatedAt	ISO datetime	
3.3 Table: ManagedPreferenceSchema

Defines default behavior for managed preferences.

Status: таблиця створена, але логіка заповнення/читання відсутня.

Field	Notes
preferenceKey	PK
baseDefault	global default
childOverride	override for children
countryOverrides	map: country → value
minAge	optional age restriction
maxAge	optional
3.4 Table: PreferenceVersions

Stores all changes.

Status: ресурс створений, але жоден хендлер не записує сюди події.

Field	Notes
versionId	PK
userId	GSI
preferenceKey	GSI
oldValue	
newValue	
timestamp	

Used for audit and revert operations.

3.5 Table: ChildLink

Maintains Adult ↔ Child relationship.

Status: таблиця створена, але API / логіка зв’язків ще не реалізовані.

Field	Notes
adultId	PK
childId	SK
3.6 Table: AgeThresholds

Defines legal age restrictions per region.

Status: таблиця існує, але не читається жодним сервісом.

Field	Notes
country	PK
ageThreshold	Integer

Example:

Ukraine → 13

EU → 18

US → 21

4. Business Logic (current vs target)

Current behavior (`backend/handlers`):

- `get_user_preferences_lambda.py` читає всі вподобання користувача з таблиці `Preferences` та повертає їх без резолюції дефолтів.
- `set_user_preferences_lambda.py` upsert-ить одну або кілька вподобань, підтримує кілька форматів тіла запиту, але поки що не підключений до API Gateway і не записує версії.
- `delete_user_preference_lambda.py` видаляє одну вподобанку та повертає оновлений список (доступний лише через прямий виклик Lambda).
- `get_user_lambda.py` повертає користувача за `userId`; ролі/права доступу наразі не застосовуються.

4.1 Roles (not enforced yet)

Adult – повний контроль над своїми та дитячими вподобаннями.

Child – обмежені дії (не може змінювати деякі preferences).

Admin – read-only аналітика.

4.2 Default Preferences Resolution Algorithm (implemented for /me/preferences)

Current behavior:

- `/me/preferences` GET викликає резольвер, який читає Users (role, country, birthDate), ManagedPreferenceSchema (всі дефолти) і AgeThresholds (визначає дитину).
- Алгоритм: baseDefault → childOverride (якщо дитина) → countryOverrides → age restrictions. Результат комбінується з фактичними overrides з таблиці Preferences і повертається клієнту.

Still missing:

- Окремий публічний `/default-preferences` ендпоінт
- Використання дефолтів у `/preferences/{userId}` або GraphQL

4.3 Preference Versioning (live for CRUD + revert)

Current state:

- PUT/DELETE operations record immutable entries in `PreferenceVersions` (action, timestamp, old/new value).
- `GET /preference-versions*` endpoints allow ops to query history per user and per preference key (with pagination tokens).
- `POST /preferences/revert` applies a historical version (sets or deletes the preference) and logs a new REVERT entry.

Still missing:

- EventBridge publishing / downstream audit worker
- GSIs / filtered queries for large tenants

4.4 Revert Operation (not implemented)

Input: userId, preferenceKey, versionId
Action:

Find previous record in PreferenceVersions

Rewrite current value

Create new version entry (revert is also a change)

4.5 Child–Parent Restrictions (partially enforced)

Child cannot override:

managed preference with childOverride = locked

age-restricted preference below threshold

Parent can write to both:

/me/preferences

/children/{childId}/preferences

Current implementation:

- Cognito-protected `/children/*` routes verify that the caller is Adult/Admin and that `childId` is linked in `ChildLinks`.
- Adults can GET/PUT/DELETE child preferences (with the same default resolver applied on read).
- All PUT/DELETE/REVERT mutations call the shared resolver to enforce `childOverride` locks and min/max age rules; blocked attempts are logged for CloudWatch metrics.
- Remaining work: richer role scopes for Admins vs Ops and propagating restrictions into future GraphQL/import flows.

5. REST API Surface

5.1 Deployed via API Gateway today

- GET /users/{userId}
- GET /users/{userId}/preferences (legacy alias for `/preferences/{userId}`)
- GET /preferences/{userId}
- PUT /preferences/{userId}
- DELETE /preferences/{userId}/{preferenceKey}
- GET /me/preferences (Cognito JWT required, returns resolved defaults + overrides)
- PUT /me/preferences (Cognito JWT required)
- DELETE /me/preferences/{preferenceKey} (Cognito JWT required)
- GET /children (Cognito Adult/Admin, lists linked child profiles)
- GET /children/{childId}/preferences (Adult/Admin, child must be linked; returns resolved prefs)
- PUT /children/{childId}/preferences (Adult/Admin, writes overrides for the child)
- DELETE /children/{childId}/preferences/{preferenceKey} (Adult/Admin, enforces managed locks/age)
- GET /preference-versions (requires query param `userId`)
- GET /preference-versions/{userId}
- GET /preference-versions/{userId}/{preferenceKey}
- POST /preferences/revert
- GET /default-preferences (read-only view of resolver output, restricted to caller’s userId for now)

5.2 Missing (must be implemented next)

- Role-aware policies (Adult vs Admin vs Ops) for `/default-preferences`, versioning, and future Ops tooling
- Dedicated `/default-preferences` admin-mode lookup (once role mapping lands)
- Public/global `GET /preference-versions` filtering (if needed for analytics)

6. Target GraphQL API (Appendix B)

NOT IMPLEMENTED AT ALL

Target schema includes:

Queries:

myPreferences

childPreferences(childId)

defaultPreferences

preferenceVersions(preferenceKey)

Mutations:

setPreference(key, value)

revertPreference(versionId)

7. Frontends (High-Level Only)
7.1 Web Portal

Two modes:

Adult Portal

Child Portal

Uses REST API.

7.2 Game Client 1

Simple REST-based client using only:

/me/preferences

/preferences/{userId}

7.3 Game Client 2

GraphQL client using AppSync.

7.4 Admin Dashboard

Read-only analytics:

preferences distribution

child behavior insights

audit trail

8. Import / Export

Not implemented.

Final design:

S3 bucket preferences-import

S3 bucket preferences-export

ImportHandler Lambda parses JSON/CSV → writes to Preferences

ExportHandler Lambda generates JSON/CSV → uploads to S3 → returns presigned URL

9. AI Recommendation Engine

NOT implemented.

Target functionality:

heuristic rules:

voice chat → disabled for children under threshold

region → adjust defaults

endpoint:

/recommendations?userId=

10. Testing Methodology (from Capstone)

Target tests:

Unit tests (lambda-level)

Integration tests (REST/GraphQL)

Contract tests (OpenAPI / GraphQL schema)

E2E tests (frontend + backend)

Performance tests (Artillery/Gatling)

Load tests

Chaos engineering (optional)

Current state:

Only 4 integration tests exist.

11. CI/CD Requirements

Target:

GitHub Actions pipeline

Lint → Test → Deploy CDK

Frontend build & deploy to S3/CloudFront

Current:

No pipeline.

Manual CDK deploy from CloudShell.

12. What Is Already Implemented
✔ DynamoDB

- `Users` і `Preferences` використовуються продакшен-кодом.
- `ManagedPreferenceSchema`, `PreferenceVersions`, `ChildLinks`, `AgeThresholds` створені, але логіка їх ще не торкається.

✔ Lambda handlers

- `get_user_preferences_lambda.py` (розгорнутий, обслуговує `/users/{userId}/preferences`, потенційно `/me/preferences`).
- `get_user_lambda.py` (розгорнутий на `/users/{userId}`).
- `set_user_preferences_lambda.py` (розгорнутий за `/preferences/{userId}` PUT і `/me/preferences` PUT, тепер зберігає `updatedAt` і записує версії змін).
- `delete_user_preference_lambda.py` (розгорнутий за `/preferences/{userId}/{preferenceKey}` DELETE та `/me/preferences/{preferenceKey}` DELETE, також пише версії з дією DELETE).
- `list_preference_versions_lambda.py` (адміністративні GET `/preference-versions*`).
- `revert_preference_lambda.py` (POST `/preferences/revert`, створює REVERT-версію і оновлює Preferences).
- `list_children_lambda.py` (GET `/children`, повертає зв’язаних дітей для дорослого користувача).

✔ REST API Gateway

- `/users/{userId}` GET
- `/users/{userId}/preferences` GET (alias)
- `/preferences/{userId}` GET/PUT
- `/preferences/{userId}/{preferenceKey}` DELETE
- `/me/preferences` GET/PUT і `/me/preferences/{preferenceKey}` DELETE (розгорнуті, але вимагають Cognito авторизації, інакше повертають 400)

✔ CDK Infrastructure

- Один стек `InfraStack` створює API Gateway, Lambda-функції для GET/PUT/DELETE і всі DynamoDB-таблиці; наступний крок — підключити Cognito authorizer, EventBridge тощо.

✔ Tests & Repo plumbing

- 4 інтеграційні тести (`tests/test_public_preferences_api.py`, `tests/test_me_lambdas.py`).
- GitHub репозиторій зв’язаний, CloudShell → GitHub синхронізація працює.

13. What Is Missing (Full Backlog)
13.1 Critical Backend Work

Implement Child/Adult roles verification (requires Cognito claims enrichment + role-based checks) — currently only `/children/*` enforce Adult/Admin; need broader policy for revert/import/etc.

Attach DynamoDB Streams → EventBridge → AuditWorker Lambda

Expose `/default-preferences` endpoint (read-only) реюзуючи існуючий резольвер

Tighten PreferenceVersions APIs with GSIs / filtering / auth once multi-tenant requirements are clear

13.2 GraphQL (AppSync)

Create GraphQL schema (based on Appendix B)

Implement resolvers

Connect DynamoDB data sources

13.3 Import/Export

Create S3 buckets

Implement ImportHandler/ExportHandler Lambdas

Add REST endpoints

13.4 AI Recommendation Engine

Create rule engine

Add endpoints

Integrate with Portal/Game Clients

13.5 Frontend Work

Web Portal UI

Game Client 1 (REST)

Game Client 2 (GraphQL)

Admin Dashboard

13.6 Testing

Unit tests for all Lambdas

Contract tests

E2E UI tests

Performance tests

13.7 CI/CD

GitHub Actions pipeline

Auto deployment of backend & frontends

CloudWatch/X-Ray dashboards

14. Summary for Cursor

This document defines:

complete architecture,

expected system behavior,

full data model,

API specification,

necessary missing components,

what is already implemented,

what must still be built.

Cursor should use this context to:

generate missing backend modules,

improve CDK infrastructure,

create missing endpoints,

build managed preferences logic,

create versioning & revert modules,

generate GraphQL schema/resolvers,

support import/export,

build AI recommendation engine,

scaffold frontend apps,

add tests,

implement CI/CD.