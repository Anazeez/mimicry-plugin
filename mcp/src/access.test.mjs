import assert from "node:assert/strict";
import test from "node:test";

import { createProtectedApi, createPublicApi } from "./access.js";

test("protected API accepts only an owner grant with render scope and matching audience", async () => {
  let forwarded = false;
  const protectedApi = createProtectedApi({
    mcpHandler: {
      fetch: () => {
        forwarded = true;
        return new Response("mcp");
      },
    },
  });
  const request = new Request("https://mimicry.example/mcp", {
    method: "POST",
  });

  const missing = await protectedApi.fetch(request, {}, {});
  assert.equal(missing.status, 401);
  assert.equal(forwarded, false);

  const wrongScope = await protectedApi.fetch(request, {}, {
    props: {
      principal_id: "github:42",
      scopes: [],
      resource: "https://mimicry.example",
    },
  });
  assert.equal(wrongScope.status, 403);
  assert.equal(forwarded, false);

  const allowed = await protectedApi.fetch(request, {}, {
    props: {
      principal_id: "github:42",
      scopes: ["artifact:render"],
      resource: "https://mimicry.example",
    },
  });
  assert.equal(allowed.status, 200);
  assert.equal(forwarded, true);
});

test("public API never forwards MCP requests to the unprotected application", async () => {
  let forwarded = false;
  const publicApi = createPublicApi({
    app: {
      fetch: () => {
        forwarded = true;
        return new Response("public");
      },
    },
  });
  for (const path of ["/mcp", "/mcp/"]) {
    const denied = await publicApi.fetch(
      new Request(`https://mimicry.example${path}`, { method: "POST" }),
      {},
      {},
    );
    assert.equal(denied.status, 404);
    assert.equal(forwarded, false);
  }

  const root = await publicApi.fetch(
    new Request("https://mimicry.example/"),
    {},
    {},
  );
  assert.equal(root.status, 200);
  assert.equal(forwarded, true);
});
