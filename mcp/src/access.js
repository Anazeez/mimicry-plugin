import { requireRenderPrincipal } from "./oauth.js";

export function createProtectedApi({ mcpHandler }) {
  return {
    async fetch(request, env, ctx) {
      if (new URL(request.url).pathname !== "/mcp") {
        return Response.json({ error: "not_found" }, { status: 404 });
      }
      try {
        requireRenderPrincipal(ctx?.props, request);
      } catch (error) {
        return Response.json(
          { error: String(error?.message || "auth_required") },
          { status: Number.isInteger(error?.status) ? error.status : 401 },
        );
      }
      return mcpHandler.fetch(request, env, ctx);
    },
  };
}

export function createPublicApi({ app }) {
  return {
    async fetch(request, env, ctx) {
      const path = new URL(request.url).pathname;
      if (path === "/mcp" || path.startsWith("/mcp/")) {
        return Response.json({ error: "not_found" }, { status: 404 });
      }
      return app.fetch(request, env, ctx);
    },
  };
}
