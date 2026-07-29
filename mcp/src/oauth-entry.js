import { OAuthProvider } from "@cloudflare/workers-oauth-provider";

import app, {
  ArtifactMimicryMCP,
  ArtifactRendererContainer,
  ArtifactStore,
} from "./index.js";
import { createProtectedApi, createPublicApi } from "./access.js";
import {
  OAUTH_PROVIDER_OPTIONS,
  createOAuthDefaultHandler,
} from "./oauth.js";

const mcpHandler = {
  fetch(request, env, ctx) {
    return ArtifactMimicryMCP.serve("/mcp").fetch(request, env, ctx);
  },
};

const protectedApi = createProtectedApi({ mcpHandler });
const publicApi = createPublicApi({ app });

export { ArtifactMimicryMCP, ArtifactRendererContainer, ArtifactStore };

export default new OAuthProvider({
  ...OAUTH_PROVIDER_OPTIONS,
  apiHandler: protectedApi,
  defaultHandler: createOAuthDefaultHandler({ publicApi }),
});
