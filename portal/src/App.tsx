import { useEffect, useMemo, useState } from "react";
import { config, getAuthorizeUrl } from "./config";
import "./app.css";

type ApiResult = {
  status: number;
  ok: boolean;
  data?: unknown;
  raw: string;
};

const TOKEN_KEY = "devPortal.idToken";
const STATE_KEY = "devPortal.oauthState";

function decodeJwt(token: string) {
  try {
    const payload = token.split(".")[1];
    const normalized = payload.replace(/-/g, "+").replace(/_/g, "/");
    const decoded = decodeURIComponent(
      atob(normalized)
        .split("")
        .map((c) => `%${`00${c.charCodeAt(0).toString(16)}`.slice(-2)}`)
        .join("")
    );
    return JSON.parse(decoded);
  } catch {
    return null;
  }
}

export function App() {
  const [idToken, setIdToken] = useState<string | null>(
    typeof window !== "undefined" ? localStorage.getItem(TOKEN_KEY) : null
  );

  const [apiResults, setApiResults] = useState<Record<string, ApiResult | null>>(
    () => ({})
  );

  const [putPayload, setPutPayload] = useState({ key: "", value: "" });
  const [deleteKey, setDeleteKey] = useState("");

  const claims = useMemo(() => (idToken ? decodeJwt(idToken) : null), [idToken]);

  useEffect(() => {
    if (!window.location.hash) return;
    const fragment = new URLSearchParams(window.location.hash.replace(/^#/, ""));
    const incomingState = fragment.get("state");
    const storedState = localStorage.getItem(STATE_KEY);
    if (incomingState && storedState && incomingState !== storedState) {
      console.warn("OAuth state mismatch, ignoring tokens");
      return;
    }

    const nextToken = fragment.get("id_token");
    if (nextToken) {
      localStorage.setItem(TOKEN_KEY, nextToken);
      setIdToken(nextToken);
      localStorage.removeItem(STATE_KEY);
      window.history.replaceState({}, document.title, window.location.pathname);
    }
  }, []);

  const configOk =
    config.cognitoDomain &&
    config.clientId &&
    config.region &&
    config.apiBaseUrl &&
    config.redirectUri;

  const login = () => {
    if (!configOk) {
      alert("Missing required config. Check your environment variables.");
      return;
    }
    const state = crypto.randomUUID();
    localStorage.setItem(STATE_KEY, state);
    window.location.href = getAuthorizeUrl(state);
  };

  const logout = () => {
    localStorage.removeItem(TOKEN_KEY);
    setIdToken(null);
  };

  const callApi = async (
    key: string,
    path: string,
    init?: RequestInit
  ): Promise<void> => {
    if (!idToken) {
      alert("Please login first.");
      return;
    }
    try {
      const response = await fetch(`${config.apiBaseUrl}${path}`, {
        ...init,
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${idToken}`,
          ...(init?.headers ?? {}),
        },
      });
      const text = await response.text();
      let data: unknown;
      try {
        data = text ? JSON.parse(text) : undefined;
      } catch {
        data = text;
      }
      setApiResults((prev) => ({
        ...prev,
        [key]: { status: response.status, ok: response.ok, data, raw: text },
      }));
    } catch (error) {
      setApiResults((prev) => ({
        ...prev,
        [key]: {
          status: 0,
          ok: false,
          data: undefined,
          raw: String(error),
        },
      }));
    }
  };

  const ResultView = ({ result }: { result?: ApiResult | null }) => {
    if (!result) return <p className="muted">No call yet.</p>;
    return (
      <div className={`result ${result.ok ? "ok" : "error"}`}>
        <strong>Status:</strong> {result.status}
        <pre>{JSON.stringify(result.data ?? result.raw, null, 2)}</pre>
      </div>
    );
  };

  return (
    <div className="app">
      <header>
        <h1>User Preferences Dev Portal</h1>
        {!configOk && (
          <p className="warning">
            Configuration incomplete. Set environment variables in
            <code>.env.development</code>.
          </p>
        )}
        <div className="auth-bar">
          {idToken ? (
            <>
              <div>
                Logged in as{" "}
                <strong>{claims?.email || claims?.username || "user"}</strong>
              </div>
              <button onClick={logout}>Logout</button>
            </>
          ) : (
            <button onClick={login}>Login</button>
          )}
        </div>
      </header>

      <main>
        <section>
          <div className="section-header">
            <div>
              <h2>GET /me/preferences</h2>
              <p>Returns resolved preferences for the current user.</p>
            </div>
            <button
              onClick={() => callApi("me", "/me/preferences")}
              disabled={!idToken}
            >
              Call endpoint
            </button>
          </div>
          <ResultView result={apiResults.me} />
        </section>

        <section>
          <div className="section-header">
            <div>
              <h2>GET /default-preferences</h2>
              <p>Shows managed defaults via the shared resolver.</p>
            </div>
            <button
              onClick={() => callApi("defaults", "/default-preferences")}
              disabled={!idToken}
            >
              Call endpoint
            </button>
          </div>
          <ResultView result={apiResults.defaults} />
        </section>

        <section>
          <div className="section-header">
            <div>
              <h2>PUT /me/preferences</h2>
              <p>Upsert a preference key/value.</p>
            </div>
          </div>
          <div className="form">
            <label>
              Preference Key
              <input
                value={putPayload.key}
                onChange={(e) =>
                  setPutPayload((prev) => ({ ...prev, key: e.target.value }))
                }
                placeholder="uiTheme"
              />
            </label>
            <label>
              Value
              <input
                value={putPayload.value}
                onChange={(e) =>
                  setPutPayload((prev) => ({ ...prev, value: e.target.value }))
                }
                placeholder="dark"
              />
            </label>
            <button
              disabled={!idToken || !putPayload.key}
              onClick={() =>
                callApi("put", "/me/preferences", {
                  method: "PUT",
                  body: JSON.stringify({
                    preferenceKey: putPayload.key,
                    value: putPayload.value,
                  }),
                })
              }
            >
              Save preference
            </button>
          </div>
          <ResultView result={apiResults.put} />
        </section>

        <section>
          <div className="section-header">
            <div>
              <h2>DELETE /me/preferences/{`{preferenceKey}`}</h2>
              <p>Remove a stored override for the current user.</p>
            </div>
          </div>
          <div className="form">
            <label>
              Preference Key
              <input
                value={deleteKey}
                onChange={(e) => setDeleteKey(e.target.value)}
                placeholder="uiTheme"
              />
            </label>
            <button
              disabled={!idToken || !deleteKey}
              onClick={() =>
                callApi("delete", `/me/preferences/${encodeURIComponent(deleteKey)}`, {
                  method: "DELETE",
                })
              }
            >
              Delete preference
            </button>
          </div>
          <ResultView result={apiResults.delete} />
        </section>
      </main>
    </div>
  );
}

