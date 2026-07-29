const OAUTH_STATE_TTL_SECONDS = 600;
const GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize";
const GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token";
const GITHUB_USER_URL = "https://api.github.com/user";

export const MIMICRY_OAUTH_SCOPES = Object.freeze(["artifact:render"]);

export const OAUTH_PROVIDER_OPTIONS = Object.freeze({
  apiRoute: Object.freeze(["/mcp"]),
  authorizeEndpoint: "/authorize",
  tokenEndpoint: "/token",
  clientRegistrationEndpoint: "/register",
  scopesSupported: MIMICRY_OAUTH_SCOPES,
  allowImplicitFlow: false,
  allowPlainPKCE: false,
  allowTokenExchangeGrant: false,
  disallowPublicClientRegistration: false,
  accessTokenTTL: 3600,
  refreshTokenTTL: 2592000,
  clientRegistrationTTL: 7776000,
  resourceMetadata: Object.freeze({
    scopes_supported: MIMICRY_OAUTH_SCOPES,
    bearer_methods_supported: Object.freeze(["header"]),
    resource_name: "Artifact Mimicry",
  }),
});

export function narrowRequestedScopes(requested) {
  const supported = new Set(MIMICRY_OAUTH_SCOPES);
  const narrowed = [...new Set(requested ?? [])]
    .filter(scope => supported.has(scope));
  if (narrowed.length === 0) throw new Error("no_supported_scope_requested");
  return narrowed;
}

export function requireRenderPrincipal(props, request) {
  if (!props?.principal_id) throw statusError("auth_required", 401);
  if (!Array.isArray(props.scopes) || !props.scopes.includes("artifact:render")) {
    throw statusError("forbidden_scope", 403);
  }
  if (props.resource !== new URL(request.url).origin) {
    throw statusError("resource_audience_mismatch", 401);
  }
  return props;
}

export function buildGrantClaims({
  githubUser,
  ownerIds,
  requestedScopes,
  resourceOrigin,
}) {
  const numericId = Number(githubUser?.id);
  if (!Number.isSafeInteger(numericId) || numericId <= 0) {
    throw new Error("invalid_github_identity");
  }
  if (!normalizeNumericIds(ownerIds).includes(String(numericId))) {
    throw statusError("owner_not_allowed", 403);
  }
  const scope = narrowRequestedScopes(requestedScopes);
  const login = String(githubUser.login ?? "");
  return {
    userId: `github-${numericId}`,
    scope,
    metadata: {
      identity_provider: "github",
      github_login: login,
      tenant_id: "personal",
      resource: resourceOrigin,
    },
    props: {
      auth_source: "oauth",
      credential_id: `github-${numericId}`,
      principal_id: `github:${numericId}`,
      github_login: login,
      tenant_id: "personal",
      scopes: scope,
      resource: resourceOrigin,
    },
  };
}

export function redactOAuthError(error) {
  return String(error?.message ?? error)
    .replace(
      /\b(access_token|refresh_token|code|client_secret)=([^\s&]+)/gi,
      "$1=[REDACTED]",
    )
    .slice(0, 500);
}

export function createOAuthDefaultHandler({
  publicApi,
  fetchImpl = fetch,
}) {
  return {
    async fetch(request, env, ctx) {
      const url = new URL(request.url);
      try {
        if (url.pathname === "/authorize" && request.method === "GET") {
          return await beginConsent(request, env);
        }
        if (url.pathname === "/authorize" && request.method === "POST") {
          return await acceptConsent(request, env);
        }
        if (url.pathname === "/callback" && request.method === "GET") {
          return await finishGitHubIdentity(request, env, fetchImpl);
        }
        return await publicApi.fetch(request, env, ctx);
      } catch (error) {
        return Response.json(
          {
            error: "oauth_request_failed",
            detail: redactOAuthError(error),
          },
          { status: oauthErrorStatus(error) },
        );
      }
    },
  };
}

async function beginConsent(request, env) {
  requireOAuthBindings(env);
  const authRequest = await env.OAUTH_PROVIDER.parseAuthRequest(request);
  const client = await env.OAUTH_PROVIDER.lookupClient(authRequest.clientId);
  if (!client) throw statusError("unknown_client", 400);
  const scopes = narrowRequestedScopes(authRequest.scope);
  const resourceOrigin = normalizedResource(
    authRequest.resource,
    new URL(request.url).origin,
  );
  const requestId = randomToken();
  const csrf = randomToken();
  await env.OAUTH_KV.put(
    stateKey(requestId),
    JSON.stringify({
      stage: "consent",
      authRequest,
      scopes,
      resourceOrigin,
      csrf,
    }),
    { expirationTtl: OAUTH_STATE_TTL_SECONDS },
  );
  const clientName = escapeHtml(
    client.clientName || client.client_name || authRequest.clientId,
  );
  return new Response(
    `<!doctype html><html><head><meta charset="utf-8">`
      + `<meta name="viewport" content="width=device-width, initial-scale=1">`
      + `<title>Authorize Artifact Mimicry</title></head>`
      + `<body><main><h1>Authorize ${clientName}</h1>`
      + `<p>Allow this client to create editable Word artifacts for you.</p>`
      + `<form method="post" action="/authorize?request=${encodeURIComponent(requestId)}">`
      + `<input type="hidden" name="csrf" value="${escapeHtml(csrf)}">`
      + `<button type="submit">Continue with GitHub</button></form>`
      + `</main></body></html>`,
    {
      headers: {
        "Content-Type": "text/html; charset=utf-8",
        "Cache-Control": "no-store",
        "Set-Cookie": csrfCookie(csrf),
      },
    },
  );
}

async function acceptConsent(request, env) {
  requireOAuthBindings(env);
  const requestId = new URL(request.url).searchParams.get("request");
  const stored = await readState(env, requestId, "consent");
  const form = await request.formData();
  const csrf = String(form.get("csrf") ?? "");
  if (
    !csrf
    || csrf !== stored.csrf
    || csrf !== readCookie(request, "artifact_mimicry_csrf")
  ) {
    throw statusError("csrf_validation_failed", 403);
  }
  const githubState = randomToken();
  await env.OAUTH_KV.delete(stateKey(requestId));
  await env.OAUTH_KV.put(
    stateKey(githubState),
    JSON.stringify({
      stage: "github",
      authRequest: stored.authRequest,
      scopes: stored.scopes,
      resourceOrigin: stored.resourceOrigin,
    }),
    { expirationTtl: OAUTH_STATE_TTL_SECONDS },
  );
  const callback = `${new URL(request.url).origin}/callback`;
  const destination = new URL(GITHUB_AUTHORIZE_URL);
  destination.searchParams.set("client_id", env.GITHUB_CLIENT_ID);
  destination.searchParams.set("redirect_uri", callback);
  destination.searchParams.set("scope", "read:user");
  destination.searchParams.set("state", githubState);
  return Response.redirect(destination, 302);
}

async function finishGitHubIdentity(request, env, fetchImpl) {
  requireOAuthBindings(env);
  const url = new URL(request.url);
  const state = url.searchParams.get("state");
  const code = url.searchParams.get("code");
  if (!state || !code) throw statusError("invalid_github_callback", 400);
  const stored = await readState(env, state, "github");
  await env.OAUTH_KV.delete(stateKey(state));
  const callback = `${url.origin}/callback`;

  const tokenResponse = await fetchImpl(GITHUB_TOKEN_URL, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      client_id: env.GITHUB_CLIENT_ID,
      client_secret: env.GITHUB_CLIENT_SECRET,
      code,
      redirect_uri: callback,
    }),
  });
  const tokenBody = await tokenResponse.json();
  if (!tokenResponse.ok || !tokenBody.access_token) {
    throw statusError(
      `github_token_exchange_failed status=${tokenResponse.status}`,
      502,
    );
  }
  const userResponse = await fetchImpl(GITHUB_USER_URL, {
    headers: {
      Accept: "application/vnd.github+json",
      Authorization: `Bearer ${tokenBody.access_token}`,
      "User-Agent": "artifact-mimicry",
      "X-GitHub-Api-Version": "2022-11-28",
    },
  });
  const githubUser = await userResponse.json();
  if (!userResponse.ok) {
    throw statusError(
      `github_identity_failed status=${userResponse.status}`,
      502,
    );
  }
  const grant = buildGrantClaims({
    githubUser,
    ownerIds: normalizeNumericIds(env.OWNER_GITHUB_IDS),
    requestedScopes: stored.scopes,
    resourceOrigin: stored.resourceOrigin,
  });
  const { redirectTo } = await env.OAUTH_PROVIDER.completeAuthorization({
    request: stored.authRequest,
    ...grant,
  });
  return Response.redirect(redirectTo, 302);
}

function requireOAuthBindings(env) {
  if (!env.OAUTH_KV || !env.OAUTH_PROVIDER) {
    throw statusError("oauth_binding_missing", 503);
  }
  if (!env.GITHUB_CLIENT_ID || !env.GITHUB_CLIENT_SECRET) {
    throw statusError("github_oauth_not_configured", 503);
  }
  if (normalizeNumericIds(env.OWNER_GITHUB_IDS).length === 0) {
    throw statusError("owner_allowlist_not_configured", 503);
  }
}

function normalizedResource(resource, requestOrigin) {
  const candidate = Array.isArray(resource) ? resource[0] : resource;
  if (!candidate) throw statusError("resource_audience_missing", 400);
  let parsed;
  try {
    parsed = new URL(candidate);
  } catch {
    throw statusError("resource_audience_invalid", 400);
  }
  if (parsed.protocol !== "https:" || parsed.origin !== requestOrigin) {
    throw statusError("resource_audience_mismatch", 400);
  }
  return parsed.origin;
}

function normalizeNumericIds(value) {
  return [...new Set(
    (Array.isArray(value) ? value : String(value || "").split(","))
      .map(item => String(item).trim())
      .filter(item => /^[1-9][0-9]*$/.test(item)),
  )];
}

async function readState(env, id, expectedStage) {
  if (!id) throw statusError("oauth_state_missing", 400);
  const raw = await env.OAUTH_KV.get(stateKey(id));
  if (!raw) throw statusError("oauth_state_invalid_or_expired", 400);
  const value = JSON.parse(raw);
  if (value.stage !== expectedStage) {
    throw statusError("oauth_state_stage_invalid", 400);
  }
  return value;
}

function randomToken() {
  const bytes = crypto.getRandomValues(new Uint8Array(24));
  return btoa(String.fromCharCode(...bytes))
    .replaceAll("+", "-")
    .replaceAll("/", "_")
    .replaceAll("=", "");
}

function stateKey(value) {
  return `oauth_state:${value}`;
}

function csrfCookie(value) {
  return `artifact_mimicry_csrf=${value}; Path=/authorize; HttpOnly; Secure; `
    + `SameSite=Lax; Max-Age=${OAUTH_STATE_TTL_SECONDS}`;
}

function readCookie(request, name) {
  const pairs = (request.headers.get("Cookie") || "").split(";");
  for (const pair of pairs) {
    const [key, ...value] = pair.trim().split("=");
    if (key === name) return value.join("=");
  }
  return "";
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function statusError(message, status) {
  return Object.assign(new Error(message), { status });
}

function oauthErrorStatus(error) {
  return Number.isInteger(error?.status) ? error.status : 400;
}
