import { DurableObject } from "cloudflare:workers";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { McpAgent } from "agents/mcp";
import { z } from "zod";
import { renderAndValidate } from "./renderer.js";

const DOCX_MIME =
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
const UNAVAILABLE =
  "Artifact Mimicry renderer unavailable.\nNo editable artifact was generated.";
const MAX_ARTIFACT_AGE_MS = 24 * 60 * 60 * 1000;

const safeFilename = (value) => {
  const normalized = String(value || "artifact-mimicry.docx")
    .replace(/[^A-Za-z0-9._-]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return (normalized || "artifact-mimicry.docx").endsWith(".docx")
    ? normalized || "artifact-mimicry.docx"
    : `${normalized}.docx`;
};

export class ArtifactStore extends DurableObject {
  async fetch(request) {
    const url = new URL(request.url);
    const [, action, artifactId] = url.pathname.split("/");
    if (!artifactId) return new Response("Not Found", { status: 404 });

    if (request.method === "POST" && action === "put") {
      const record = {
        bytes: await request.arrayBuffer(),
        filename: safeFilename(request.headers.get("x-filename")),
        expiresAt: Number(request.headers.get("x-expires-at"))
      };
      await this.ctx.storage.put(artifactId, record);
      return new Response(null, { status: 204 });
    }

    if (request.method === "GET" && action === "get") {
      const record = await this.ctx.storage.get(artifactId);
      if (!record || Date.now() >= record.expiresAt) {
        if (record) await this.ctx.storage.delete(artifactId);
        return new Response("Artifact expired or not found", { status: 404 });
      }
      return new Response(record.bytes, {
        headers: {
          "content-type": DOCX_MIME,
          "content-disposition": `attachment; filename="${record.filename}"`,
          "cache-control": "private, no-store"
        }
      });
    }

    return new Response("Not Found", { status: 404 });
  }
}

export class ArtifactMimicryMCP extends McpAgent {
  server = new McpServer(
    { name: "artifact-mimicry", version: "0.4.0" },
    {
      instructions:
        "For Artifact Mimicry DOCX requests, call execute after decomposing the reference into the supplied native-shape task schema. Never manually construct, reuse, or substitute an artifact. If execute is unavailable, return exactly: Artifact Mimicry renderer unavailable. No editable artifact was generated."
    }
  );

  async init() {
    this.server.registerTool(
      "execute",
      {
        title: "Render editable Word artifact",
        description:
          "Required execution path for Artifact Mimicry Word requests. Accepts the reference decomposition as a native-shape task, runs deterministic DOCX rendering and structural validation, and returns a fresh downloadable DOCX. Never emulate this tool manually.",
        inputSchema: {
          task: z
            .any()
            .describe(
              "Artifact Mimicry task matching mimicry-task.schema.json, including page dimensions and editable native elements."
            ),
          expectations: z
            .any()
            .optional()
            .describe(
              "Fail-closed structural expectations including shape counts, required text, RTL labels, and required shape names."
            ),
          filename: z.string().optional().describe("Desired .docx filename.")
        },
        outputSchema: {
          status: z.literal("PASS"),
          filename: z.string(),
          download_url: z.string().url(),
          expires_at: z.string(),
          validation: z.record(z.string(), z.boolean())
        },
        annotations: {
          readOnlyHint: false,
          destructiveHint: false,
          openWorldHint: false
        }
      },
      async ({ task, expectations = {}, filename }) => {
        try {
          const { bytes, report } = renderAndValidate(task, expectations);
          const artifactId = crypto.randomUUID();
          const expiresAt = Date.now() + MAX_ARTIFACT_AGE_MS;
          const outputFilename = safeFilename(filename);
          const storeId = this.env.ARTIFACT_STORE.idFromName("global");
          const store = this.env.ARTIFACT_STORE.get(storeId);
          const stored = await store.fetch(
            new Request(`https://artifact-store/put/${artifactId}`, {
              method: "POST",
              headers: {
                "x-filename": outputFilename,
                "x-expires-at": String(expiresAt)
              },
              body: bytes
            })
          );
          if (!stored.ok) throw new Error("artifact storage failed");

          const downloadUrl = `${this.env.PUBLIC_BASE_URL}/artifacts/${artifactId}/${encodeURIComponent(outputFilename)}`;
          const structuredContent = {
            status: "PASS",
            filename: outputFilename,
            download_url: downloadUrl,
            expires_at: new Date(expiresAt).toISOString(),
            validation: report.gates
          };
          return {
            structuredContent,
            content: [
              {
                type: "text",
                text: `Validated editable DOCX created: ${downloadUrl}`
              },
              {
                type: "resource_link",
                uri: downloadUrl,
                name: outputFilename,
                mimeType: DOCX_MIME,
                description: "Fresh validated editable Artifact Mimicry DOCX"
              }
            ]
          };
        } catch (error) {
          const message =
            error instanceof Error && error.message.startsWith("Artifact Mimicry validation failed")
              ? error.message
              : UNAVAILABLE;
          return {
            isError: true,
            content: [{ type: "text", text: message }]
          };
        }
      }
    );
  }
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/") {
      return Response.json({
        name: "artifact-mimicry",
        version: "0.4.0",
        status: "ok",
        mcp: "/mcp"
      });
    }
    if (request.method === "GET" && url.pathname.startsWith("/artifacts/")) {
      const [, , artifactId] = url.pathname.split("/");
      const store = env.ARTIFACT_STORE.get(env.ARTIFACT_STORE.idFromName("global"));
      return store.fetch(new Request(`https://artifact-store/get/${artifactId}`));
    }
    if (request.method === "OPTIONS" && url.pathname === "/mcp") {
      return new Response(null, {
        status: 204,
        headers: {
          "access-control-allow-origin": "*",
          "access-control-allow-methods": "POST, GET, DELETE, OPTIONS",
          "access-control-allow-headers": "content-type, mcp-session-id",
          "access-control-expose-headers": "Mcp-Session-Id"
        }
      });
    }
    return ArtifactMimicryMCP.serve("/mcp").fetch(request, env, ctx);
  }
};
