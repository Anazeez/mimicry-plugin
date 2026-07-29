import { OAuthProvider } from "@cloudflare/workers-oauth-provider";

import app, {
  ArtifactMimicryMCP,
  ArtifactMimicryMCPV2,
  ArtifactMimicryMCPV3,
  ArtifactRenderWorkflow,
  ArtifactRendererContainer,
  ArtifactRendererContainerV2,
  ArtifactRendererContainerV3,
  ArtifactRendererContainerV4,
  ArtifactRendererContainerV5,
  ArtifactRendererContainerV6,
  ArtifactStore,
} from "./index.js";
import { createProtectedApi, createPublicApi } from "./access.js";
import {
  OAUTH_PROVIDER_OPTIONS,
  createOAuthDefaultHandler,
} from "./oauth.js";

const mcpHandler = {
  fetch(request, env, ctx) {
    return ArtifactMimicryMCPV3.serve("/mcp").fetch(request, env, ctx);
  },
};

const protectedApi = createProtectedApi({ mcpHandler });
const publicApi = createPublicApi({ app });

export {
  ArtifactMimicryMCP,
  ArtifactMimicryMCPV2,
  ArtifactMimicryMCPV3,
  ArtifactRenderWorkflow,
  ArtifactRendererContainer,
  ArtifactRendererContainerV2,
  ArtifactRendererContainerV3,
  ArtifactRendererContainerV4,
  ArtifactRendererContainerV5,
  ArtifactRendererContainerV6,
  ArtifactStore
};

export default new OAuthProvider({
  ...OAUTH_PROVIDER_OPTIONS,
  apiHandler: protectedApi,
  defaultHandler: createOAuthDefaultHandler({ publicApi }),
});
