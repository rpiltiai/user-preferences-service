# User Preferences Dev Portal

This React + Vite SPA is a lightweight tool for authenticating against the Cognito User Pool and smoke-testing the User Preferences API Gateway.

## Prerequisites

- Node.js 18+ and npm
- Cognito User Pool with a hosted UI client

## Configuration

Create `portal/.env.development` (and optionally `.env.production`) with the following settings:

```dotenv
VITE_COGNITO_DOMAIN=https://your-domain.auth.eu-north-1.amazoncognito.com
VITE_COGNITO_CLIENT_ID=YOUR_APP_CLIENT_ID
VITE_COGNITO_REGION=eu-north-1
VITE_COGNITO_REDIRECT_URI=http://localhost:5173/callback
VITE_COGNITO_SCOPE=openid email profile
VITE_COGNITO_RESPONSE_TYPE=token
VITE_API_BASE_URL=https://5h1aha8547.execute-api.eu-north-1.amazonaws.com/prod
```

> ⚠️ Do not commit real secrets or tokens. Keep environment files local.

## Scripts

```bash
npm install        # install dependencies
npm run dev        # start Vite dev server on http://localhost:5173
npm run build      # type-check + build a production bundle
npm run preview    # serve the production bundle locally
```

## Usage

1. Run `npm run dev`.
2. Click **Login** to initiate the Cognito Hosted UI flow.
3. Use the panels to call:
   - `GET /me/preferences`
   - `GET /default-preferences`
   - `PUT /me/preferences`
   - `DELETE /me/preferences/{preferenceKey}`

Tokens are stored in memory and `localStorage` for convenience. Use **Logout** to clear them. All API requests include `Authorization: Bearer <id_token>`.

