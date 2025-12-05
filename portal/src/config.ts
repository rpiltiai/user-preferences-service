export interface PortalConfig {
  cognitoDomain: string;
  clientId: string;
  region: string;
  redirectUri: string;
  scope: string;
  responseType: string;
  apiBaseUrl: string;
}

const fallbackRedirect =
  typeof window !== "undefined" ? window.location.origin + "/callback" : "";

export const config: PortalConfig = {
  cognitoDomain: import.meta.env.VITE_COGNITO_DOMAIN ?? "",
  clientId: import.meta.env.VITE_COGNITO_CLIENT_ID ?? "",
  region: import.meta.env.VITE_COGNITO_REGION ?? "",
  redirectUri: import.meta.env.VITE_COGNITO_REDIRECT_URI ?? fallbackRedirect,
  scope: import.meta.env.VITE_COGNITO_SCOPE ?? "openid email profile",
  responseType: import.meta.env.VITE_COGNITO_RESPONSE_TYPE ?? "token",
  apiBaseUrl: import.meta.env.VITE_API_BASE_URL ?? "",
};

export function getAuthorizeUrl(state: string) {
  const params = new URLSearchParams({
    client_id: config.clientId,
    response_type: config.responseType,
    scope: config.scope,
    redirect_uri: config.redirectUri,
    state,
  });

  return `${config.cognitoDomain.replace(/\/+$/, "")}/oauth2/authorize?${params.toString()}`;
}

