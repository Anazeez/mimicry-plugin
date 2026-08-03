import assert from "node:assert/strict";
import test from "node:test";

import {
  MIMICRY_OAUTH_SCOPES,
  OAUTH_PROVIDER_OPTIONS,
  buildGrantClaims,
  createOAuthDefaultHandler,
  narrowRequestedScopes,
  redactOAuthError,
} from "./oauth.js";

test("OAuth uses authorization code with S256 and one render scope", () => {
  assert.equal(OAUTH_PROVIDER_OPTIONS.allowPlainPKCE, false);
  assert.equal(OAUTH_PROVIDER_OPTIONS.allowImplicitFlow, false);
  assert.equal(OAUTH_PROVIDER_OPTIONS.allowTokenExchangeGrant, false);
  assert.deepEqual(OAUTH_PROVIDER_OPTIONS.apiRoute, ["/mcp"]);
  assert.deepEqual(MIMICRY_OAUTH_SCOPES, ["artifact:render"]);
  assert.deepEqual(
    narrowRequestedScopes(["artifact:render", "admin", "artifact:render"]),
    ["artifact:render"],
  );
  assert.throws(
    () => narrowRequestedScopes(["admin"]),
    /no_supported_scope_requested/,
  );
});

test("grant claims allow only the configured GitHub owner", () => {
  assert.deepEqual(
    buildGrantClaims({
      githubUser: { id: 42, login: "owner" },
      ownerIds: ["42"],
      requestedScopes: ["artifact:render", "admin"],
      resourceOrigin: "https://mimicry.example",
    }),
    {
      userId: "github-42",
      scope: ["artifact:render"],
      metadata: {
        identity_provider: "github",
        github_login: "owner",
        tenant_id: "personal",
        resource: "https://mimicry.example",
      },
      props: {
        auth_source: "oauth",
        credential_id: "github-42",
        principal_id: "github:42",
        github_login: "owner",
        tenant_id: "personal",
        scopes: ["artifact:render"],
        resource: "https://mimicry.example",
      },
    },
  );
  assert.throws(
    () =>
      buildGrantClaims({
        githubUser: { id: 99, login: "stranger" },
        ownerIds: ["42"],
        requestedScopes: ["artifact:render"],
        resourceOrigin: "https://mimicry.example",
      }),
    /owner_not_allowed/,
  );
});

test("authorization rejects a different resource audience and mismatched CSRF", async () => {
  const kv = memoryKv();
  const handler = createOAuthDefaultHandler({
    publicApi: { fetch: () => new Response("public") },
  });
  const wrongAudience = await handler.fetch(
    new Request("https://mimicry.example/authorize?client_id=client"),
    oauthEnvironment(kv, { resource: "https://other.example" }),
  );
  assert.equal(wrongAudience.status, 400);
  assert.equal((await wrongAudience.json()).detail, "resource_audience_mismatch");

  const consent = await handler.fetch(
    new Request("https://mimicry.example/authorize?client_id=client"),
    oauthEnvironment(kv),
  );
  assert.equal(consent.status, 200);
  assert.match(consent.headers.get("set-cookie"), /HttpOnly; Secure; SameSite=Lax/);
  const html = await consent.text();
  const requestId = html.match(/request=([^"]+)/)[1];
  const response = await handler.fetch(
    new Request(`https://mimicry.example/authorize?request=${requestId}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/x-www-form-urlencoded",
        Cookie: "artifact_mimicry_csrf=wrong",
      },
      body: "csrf=also-wrong",
    }),
    oauthEnvironment(kv),
  );
  assert.equal(response.status, 403);
  assert.equal((await response.json()).detail, "csrf_validation_failed");
});

test("GitHub access token never enters the completed assistant grant", async () => {
  const kv = memoryKv();
  let completedGrant;
  const env = oauthEnvironment(kv, {}, grant => {
    completedGrant = grant;
    return { redirectTo: "https://chatgpt.com/oauth/callback?code=done" };
  });
  const handler = createOAuthDefaultHandler({
    publicApi: { fetch: () => new Response("public") },
    fetchImpl: async url => {
      if (url === "https://github.com/login/oauth/access_token") {
        return Response.json({ access_token: "github-secret-token" });
      }
      if (url === "https://api.github.com/user") {
        return Response.json({ id: 42, login: "owner" });
      }
      throw new Error(`unexpected URL ${url}`);
    },
  });
  const consent = await handler.fetch(
    new Request("https://mimicry.example/authorize?client_id=client"),
    env,
  );
  const cookie = consent.headers.get("set-cookie").split(";")[0];
  const html = await consent.text();
  const requestId = html.match(/request=([^"]+)/)[1];
  const csrf = html.match(/name="csrf" value="([^"]+)"/)[1];
  const githubRedirect = await handler.fetch(
    new Request(`https://mimicry.example/authorize?request=${requestId}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/x-www-form-urlencoded",
        Cookie: cookie,
      },
      body: `csrf=${encodeURIComponent(csrf)}`,
    }),
    env,
  );
  const githubState = new URL(githubRedirect.headers.get("location"))
    .searchParams.get("state");
  const completed = await handler.fetch(
    new Request(
      `https://mimicry.example/callback?code=github-code&state=${githubState}`,
    ),
    env,
  );
  assert.equal(completed.status, 302);
  assert.equal(completedGrant.props.principal_id, "github:42");
  assert.doesNotMatch(JSON.stringify(completedGrant), /github-secret-token/);
});

test("owner GitHub bearer credential completes a one-time CLI authorization", async () => {
  const kv = memoryKv();
  let completedGrant;
  const env = oauthEnvironment(kv, {
    redirectUri: "http://127.0.0.1:38195/callback/codex",
  }, grant => {
    completedGrant = grant;
    return {
      redirectTo:
        "http://127.0.0.1:38195/callback/codex?code=issued&state=client-state",
    };
  });
  const handler = createOAuthDefaultHandler({
    publicApi: { fetch: () => new Response("public") },
    fetchImpl: async (url, init) => {
      assert.equal(url, "https://api.github.com/user");
      assert.equal(init.headers.Authorization, "Bearer github-cli-token");
      return Response.json({ id: 42, login: "owner" });
    },
  });
  const consent = await handler.fetch(
    new Request("https://mimicry.example/authorize?client_id=client"),
    env,
  );
  const cookie = consent.headers.get("set-cookie").split(";")[0];
  const html = await consent.text();
  const requestId = html.match(/request=([^"]+)/)[1];
  const csrf = html.match(/name="csrf" value="([^"]+)"/)[1];
  const request = () => new Request(
    `https://mimicry.example/authorize?request=${requestId}`,
    {
      method: "POST",
      headers: {
        Authorization: "Bearer github-cli-token",
        "Content-Type": "application/x-www-form-urlencoded",
        Cookie: cookie,
      },
      body: `csrf=${encodeURIComponent(csrf)}`,
    },
  );

  const completed = await handler.fetch(request(), env);
  assert.equal(completed.status, 302);
  assert.equal(
    completed.headers.get("location"),
    "http://127.0.0.1:38195/callback/codex?code=issued&state=client-state",
  );
  assert.equal(completedGrant.props.principal_id, "github:42");
  assert.doesNotMatch(JSON.stringify(completedGrant), /github-cli-token/);

  const replay = await handler.fetch(request(), env);
  assert.equal(replay.status, 400);
  assert.equal((await replay.json()).detail, "oauth_state_invalid_or_expired");
});

test("OAuth errors redact credential-shaped values", () => {
  const redacted = redactOAuthError(
    "failed access_token=token-value refresh_token=refresh-value code=code-value client_secret=secret-value",
  );
  assert.doesNotMatch(
    redacted,
    /token-value|refresh-value|code-value|secret-value/,
  );
  assert.match(redacted, /\[REDACTED\]/);
});

function oauthEnvironment(kv, authOverrides = {}, complete = () => ({
  redirectTo: "https://chatgpt.com/callback",
})) {
  return {
    OAUTH_KV: kv,
    GITHUB_CLIENT_ID: "github-client",
    GITHUB_CLIENT_SECRET: "github-client-secret",
    OWNER_GITHUB_IDS: "42",
    OAUTH_PROVIDER: {
      parseAuthRequest: async () => ({
        responseType: "code",
        clientId: "client",
        redirectUri: "https://chatgpt.com/oauth/callback",
        scope: ["artifact:render", "admin"],
        state: "client-state",
        codeChallenge: "challenge",
        codeChallengeMethod: "S256",
        resource: "https://mimicry.example",
        ...authOverrides,
      }),
      lookupClient: async () => ({ clientName: "ChatGPT" }),
      completeAuthorization: async grant => complete(grant),
    },
  };
}

function memoryKv() {
  const values = new Map();
  return {
    get: async key => values.get(key) ?? null,
    put: async (key, value) => values.set(key, value),
    delete: async key => values.delete(key),
  };
}
