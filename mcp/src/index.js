import { DurableObject, WorkflowEntrypoint } from "cloudflare:workers";
import { Container, getRandom } from "@cloudflare/containers";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { McpAgent } from "agents/mcp";
import { z } from "zod";
import {
  EXECUTE_TOOL_META,
  referenceFileSchema,
} from "./file-handoff.js";
import { ContainerRenderError } from "./container-client.js";
import {
  artifactJobPath,
  isArtifactJobId,
  jobStorageKey,
  normalizeArtifactJobFailure,
  withWorkflowStatus,
} from "./job-capability.js";
import { executeReferencePipeline } from "./pipeline.js";
import {
  mimicryHintsInputSchema,
  resolveMimicryHints
} from "./task-schema.js";
import {
  ARTIFACT_WORKFLOW_STEP_CONFIG,
  launchArtifactWorkflow,
} from "./workflow-launch.js";

const DOCX_MIME =
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
const UNAVAILABLE =
  "Artifact Mimicry renderer unavailable.\nNo editable artifact was generated.";
const MAX_ARTIFACT_AGE_MS = 24 * 60 * 60 * 1000;
const JOB_POLL_MS = 2_000;
const JOB_LONG_POLL_MS = 95_000;
const ARTIFACT_TOOL_STATUSES = [
  "PROCESSING",
  "PASS",
  "EDITABILITY_FAILED",
  "FIDELITY_FAILED",
  "VALIDATION_INCOMPLETE",
  "PACKAGE_INVALID",
  "GENERATION_FAILED",
  "UNSUPPORTED_NATIVE_RECONSTRUCTION",
  "RASTER_FALLBACK_PROHIBITED",
];
const OPENAI_APPS_CHALLENGE_TOKEN =
  "qFMgLq4heF1lgZGB2Nr2mhWSXVwKFkqiiBr95gI1tqc";

const publicPage = (title, content) =>
  new Response(
    `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>${title} · Artifact Mimicry</title>
  <style>
    :root { color-scheme: dark; font-family: ui-sans-serif, system-ui, sans-serif; }
    body { margin: 0; background: #071c1b; color: #e9f6f1; }
    main { max-width: 720px; margin: 0 auto; padding: 64px 24px 96px; }
    a { color: #a9ead4; }
    h1 { font-size: clamp(2rem, 7vw, 3.5rem); line-height: 1; margin: 0 0 24px; }
    h2 { margin-top: 36px; }
    p, li { color: #c6d8d2; line-height: 1.65; }
    .brand { color: #79cdb1; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; }
    .updated { color: #8fa7a0; font-size: .9rem; margin-bottom: 40px; }
  </style>
</head>
<body>
  <main>
    <div class="brand">Artifact Mimicry</div>
    <h1>${title}</h1>
    <div class="updated">Effective July 26, 2026</div>
    ${content}
  </main>
</body>
</html>`,
    {
      headers: {
        "content-type": "text/html; charset=utf-8",
        "cache-control": "public, max-age=300"
      }
    }
  );

const publicPages = {
  "/support": () =>
    publicPage(
      "Customer support",
      `<p>For help with Artifact Mimicry, report the problem through the project’s public support tracker.</p>
       <p><a href="https://github.com/Anazeez/mimicry-plugin/issues">Open Artifact Mimicry support</a></p>
       <p>Include the requested output type, the error shown, and whether the issue occurred on ChatGPT web, iOS, Android, or Codex. Do not include confidential source documents in a public issue.</p>`
    ),
  "/privacy": () =>
    publicPage(
      "Privacy policy",
      `<h2>Data processed</h2>
       <p>Artifact Mimicry processes task instructions and document-layout data submitted to its tool to generate an editable Microsoft Word document. It does not require an Artifact Mimicry account.</p>
       <h2>Temporary artifacts</h2>
       <p>Generated DOCX files are stored at an unlisted download address for up to 24 hours and are then treated as expired. Download links should not be shared with people who should not access the document.</p>
       <h2>Use and disclosure</h2>
       <p>Submitted data is used only to provide and secure the requested rendering service. Artifact Mimicry does not sell personal data or use submitted document content for advertising.</p>
       <h2>Infrastructure</h2>
       <p>The service runs on Cloudflare infrastructure, which may process limited technical data needed to deliver and protect the service.</p>
       <h2>Contact</h2>
       <p>Privacy questions may be submitted through the <a href="https://github.com/Anazeez/mimicry-plugin/issues">support tracker</a>. Do not post confidential information in a public issue.</p>`
    ),
  "/terms": () =>
    publicPage(
      "Terms of service",
      `<h2>Service</h2>
       <p>Artifact Mimicry generates editable DOCX artifacts from user-provided instructions and layout specifications. Generated download links expire after approximately 24 hours.</p>
       <h2>Your responsibilities</h2>
       <p>You must have the right to use the material you submit. You may not use the service to violate law, intellectual-property rights, privacy rights, or platform policies.</p>
       <h2>Outputs</h2>
       <p>You are responsible for reviewing generated documents before relying on, publishing, or distributing them. The service may refuse generation when required geometry or validation cannot be resolved.</p>
       <h2>Availability and warranty</h2>
       <p>The service is provided as available without guarantees of uninterrupted operation or fitness for a particular purpose. Features may change to improve safety, reliability, or compliance.</p>
       <h2>Contact</h2>
       <p>Questions may be submitted through the <a href="https://github.com/Anazeez/mimicry-plugin/issues">support tracker</a>.</p>`
    )
};

const safeFilename = (value) => {
  const normalized = String(value || "artifact-mimicry.docx")
    .replace(/[^A-Za-z0-9._-]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return (normalized || "artifact-mimicry.docx").endsWith(".docx")
    ? normalized || "artifact-mimicry.docx"
    : `${normalized}.docx`;
};

const safeFailureDiagnostic = (error) => {
  const raw = String(error?.message || error?.name || "unknown runtime failure")
    .replace(/https?:\/\/\S+/gi, "[url]")
    .replace(/[A-Za-z0-9_-]{32,}/g, "[redacted]")
    .replace(/\s+/g, " ")
    .trim();
  return raw.slice(0, 240);
};

const compactValidationReport = (report) => {
  if (!report || typeof report !== "object") return null;
  const scalarMetrics = Object.fromEntries(
    Object.entries(report.metrics || {}).filter(
      ([, value]) => ["number", "string", "boolean"].includes(typeof value) || value === null,
    ),
  );
  return {
    status: report.status,
    version: report.version,
    gates: report.gates || {},
    metrics: scalarMetrics,
    editability:
      report.editability && typeof report.editability === "object"
        ? Object.fromEntries(
            Object.entries(report.editability).filter(
              ([, value]) =>
                ["number", "string", "boolean"].includes(typeof value) ||
                value === null,
            ),
          )
        : {},
    findings: Array.isArray(report.findings) ? report.findings.slice(0, 24) : [],
  };
};

const artifactStoreForEnv = (env) =>
  env.ARTIFACT_STORE.get(env.ARTIFACT_STORE.idFromName("global"));

const writeArtifactJobForEnv = async (env, jobId, record) => {
  const response = await artifactStoreForEnv(env).fetch(
    new Request(`https://artifact-store/job-put/${jobId}`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(record),
    }),
  );
  if (!response.ok) throw new Error("artifact job storage failed");
};

const runArtifactJob = async (
  env,
  { jobId, referenceFile, hints, task, filename },
) => {
  try {
    const resolvedHints = resolveMimicryHints({ hints, task });
    const renderer = await getRandom(env.RENDERER, 1);
    const { bytes, report } = await executeReferencePipeline({
      referenceFile,
      hints: resolvedHints,
      renderer,
    });
    const artifactId = crypto.randomUUID();
    const expiresAt = Date.now() + MAX_ARTIFACT_AGE_MS;
    const outputFilename = safeFilename(filename);
    const stored = await artifactStoreForEnv(env).fetch(
      new Request(`https://artifact-store/put/${artifactId}`, {
        method: "POST",
        headers: {
          "x-filename": outputFilename,
          "x-expires-at": String(expiresAt),
        },
        body: bytes,
      }),
    );
    if (!stored.ok) throw new Error("artifact storage failed");
    const result = {
      status: "PASS",
      filename: outputFilename,
      download_url: `${env.PUBLIC_BASE_URL}/artifacts/${artifactId}/${encodeURIComponent(outputFilename)}`,
      expires_at: new Date(expiresAt).toISOString(),
      validation: report.gates,
      validation_report: compactValidationReport(report),
    };
    await writeArtifactJobForEnv(env, jobId, result);
    return result;
  } catch (error) {
    const result = normalizeArtifactJobFailure({
      code: error instanceof ContainerRenderError ? error.code : error?.code,
      message:
        error instanceof ContainerRenderError
          ? error.message
          : UNAVAILABLE,
      diagnostic:
        error instanceof ContainerRenderError && error.diagnostic
          ? safeFailureDiagnostic({ message: error.diagnostic })
          : safeFailureDiagnostic(error),
      report:
        error instanceof ContainerRenderError && error.report
          ? compactValidationReport(error.report)
          : null,
    });
    await writeArtifactJobForEnv(env, jobId, result);
    return result;
  }
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

    if (request.method === "POST" && action === "job-put") {
      if (!isArtifactJobId(artifactId)) {
        return new Response("Invalid job id", { status: 400 });
      }
      await this.ctx.storage.put(jobStorageKey(artifactId), {
        payload: await request.json(),
        expiresAt: Date.now() + MAX_ARTIFACT_AGE_MS,
      });
      return new Response(null, { status: 204 });
    }

    if (request.method === "GET" && action === "job-get") {
      if (!isArtifactJobId(artifactId)) {
        return new Response("Invalid job id", { status: 400 });
      }
      const storageKey = jobStorageKey(artifactId);
      const record = await this.ctx.storage.get(storageKey);
      if (!record || Date.now() >= record.expiresAt) {
        if (record) await this.ctx.storage.delete(storageKey);
        return new Response("Artifact job expired or not found", { status: 404 });
      }
      return Response.json(record.payload, {
        headers: { "cache-control": "private, no-store" },
      });
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

export class ArtifactRendererContainer extends Container {
  defaultPort = 8080;
  requiredPorts = [8080];
  sleepAfter = "2m";
  enableInternet = false;
  pingEndpoint = "localhost/health";
}

// A new class identity forces Cloudflare to instantiate the image attached to
// this deployment instead of reusing a pre-deployment container instance.
export class ArtifactRendererContainerV2 extends ArtifactRendererContainer {}
export class ArtifactRendererContainerV3 extends ArtifactRendererContainer {}
export class ArtifactRendererContainerV4 extends ArtifactRendererContainer {}
export class ArtifactRendererContainerV5 extends ArtifactRendererContainer {}
export class ArtifactRendererContainerV6 extends ArtifactRendererContainer {}
export class ArtifactRendererContainerV7 extends ArtifactRendererContainer {}
export class ArtifactRendererContainerV8 extends ArtifactRendererContainer {}
export class ArtifactRendererContainerV9 extends ArtifactRendererContainer {}
export class ArtifactRendererContainerV10 extends ArtifactRendererContainer {}
export class ArtifactRendererContainerV11 extends ArtifactRendererContainer {}
export class ArtifactRendererContainerV12 extends ArtifactRendererContainer {}
export class ArtifactRendererContainerV13 extends ArtifactRendererContainer {}
export class ArtifactRendererContainerV14 extends ArtifactRendererContainer {}

export class ArtifactRenderWorkflow extends WorkflowEntrypoint {
  async run(event, step) {
    try {
      return await step.do(
        "render and validate editable DOCX",
        ARTIFACT_WORKFLOW_STEP_CONFIG,
        () => runArtifactJob(this.env, event.payload),
      );
    } catch (error) {
      const result = {
        status: "FAILED",
        message: UNAVAILABLE,
        diagnostic: `WORKFLOW_FAILED: ${safeFailureDiagnostic(error)}`,
      };
      await writeArtifactJobForEnv(this.env, event.payload.jobId, result);
      return result;
    }
  }
}

export class ArtifactMimicryMCP extends McpAgent {
  server = new McpServer(
    { name: "artifact-mimicry", version: "1.0.0" },
    {
      instructions:
        "For Artifact Mimicry DOCX requests, call execute with the attached reference file, then call await_result with the returned job_id until it returns PASS or a fail-closed error. Do both automatically from the user's single prompt; never ask the user to poll or re-prompt. The service downloads the reference, measures a generic editable scene graph, constructs the DOCX through LibreOffice, reopens and renders the saved file, and independently validates geometry and visual fidelity. Never manually decompose, construct, reuse, or substitute an artifact. If execution fails, report the exact fail-closed result."
    }
  );

  artifactStore() {
    return artifactStoreForEnv(this.env);
  }

  async writeArtifactJob(jobId, record) {
    return writeArtifactJobForEnv(this.env, jobId, record);
  }

  async readArtifactJob(jobId, longPoll = false) {
    const deadline = Date.now() + (longPoll ? JOB_LONG_POLL_MS : 0);
    do {
      const response = await this.artifactStore().fetch(
        new Request(`https://artifact-store/job-get/${jobId}`),
      );
      const record =
        response.status === 404
          ? null
          : response.ok
            ? await response.json()
            : (() => {
                throw new Error("artifact job retrieval failed");
              })();
      if (!record || record.status !== "PROCESSING") return record;
      if (Date.now() >= deadline) return record;
      await new Promise((resolve) => setTimeout(resolve, JOB_POLL_MS));
    } while (true);
  }

  async artifactJobResponse(jobId, longPoll = true, legacyPass = false) {
    const record = await this.readArtifactJob(jobId, longPoll);
    if (!record) {
      return {
        isError: true,
        content: [{ type: "text", text: "Artifact Mimicry job not found." }]
      };
    }
    if (record.status === "FAILED") {
      const status = ARTIFACT_TOOL_STATUSES.includes(record.error_code)
        ? record.error_code
        : "VALIDATION_INCOMPLETE";
      return {
        structuredContent: {
          status,
          job_id: jobId,
          message: record.message,
          diagnostic: record.diagnostic,
          validation_report: record.validation_report,
        },
        content: [
          {
            type: "text",
            text: `${status}: ${record.message}`,
          },
        ],
        _meta: {
          "artifact-mimicry/validation-report": record.validation_report,
          "artifact-mimicry/failure-diagnostic": record.diagnostic,
        },
      };
    }
    if (record.status === "PROCESSING") {
      return {
        structuredContent: { status: "PROCESSING", job_id: jobId },
        content: [
          {
            type: "text",
            text: `Rendering is still in progress. Call await_result with job_id ${jobId}. If await_result is not visible in a cached connector session, call execute again with expectations.job_id set to ${jobId}.`
          }
        ]
      };
    }
    const structuredContent = legacyPass
      ? record
      : { ...record, job_id: jobId };
    return {
      structuredContent,
      content: [
        {
          type: "text",
          text: `Validated editable DOCX created: ${record.download_url}`
        },
        {
          type: "resource_link",
          uri: record.download_url,
          name: record.filename,
          mimeType: DOCX_MIME,
          description: "Fresh validated editable Artifact Mimicry DOCX"
        }
      ]
    };
  }

  async init() {
    this.server.registerTool(
      "execute",
      {
        title: "Render editable Word artifact",
        description:
          "Starts the required durable Artifact Mimicry rendering job. After this returns PROCESSING, immediately call await_result with its job_id. Do not ask the user to poll or re-prompt.",
        inputSchema: {
          reference_file: referenceFileSchema,
          hints: mimicryHintsInputSchema
            .optional()
            .describe(
              "Optional non-geometric guidance or editable text replacements. The reference controls measured geometry."
            ),
          task: mimicryHintsInputSchema
            .optional()
            .describe(
              "Backward-compatible alias for hints used by already-installed connectors."
            ),
          expectations: z
            .unknown()
            .optional()
            .describe(
              "Backward-compatible installed-connector field. It cannot override measured geometry or validation. A cached connector may pass the returned job_id here as expectations.job_id to await the same job."
            ),
          filename: z.string().optional().describe("Desired .docx filename.")
        },
        outputSchema: {
          status: z.enum(ARTIFACT_TOOL_STATUSES),
          job_id: z.string().optional(),
          filename: z.string().optional(),
          download_url: z.string().url().optional(),
          expires_at: z.string().optional(),
          validation: z.record(z.string(), z.boolean()).optional(),
          validation_report: z.unknown().optional(),
          message: z.string().optional(),
          diagnostic: z.string().optional(),
        },
        annotations: {
          readOnlyHint: false,
          destructiveHint: false,
          openWorldHint: true
        },
        _meta: EXECUTE_TOOL_META
      },
      async ({
        reference_file: referenceFile,
        hints,
        task,
        expectations,
        filename
      }) => {
        try {
          const compatibilityJobId =
            task && typeof task === "object" && typeof task.job_id === "string"
              ? task.job_id
              : task &&
                  typeof task === "object" &&
                  typeof task.instructions === "string" &&
                  /^JOB_ID:[0-9a-f-]{36}$/i.test(task.instructions.trim())
                ? task.instructions.trim().slice("JOB_ID:".length)
              : expectations &&
                  typeof expectations === "object" &&
                  typeof expectations.job_id === "string"
                ? expectations.job_id
                : null;
          if (compatibilityJobId) {
            return this.artifactJobResponse(
              z.string().uuid().parse(compatibilityJobId),
              true,
              true
            );
          }
          referenceFileSchema.parse(referenceFile);
          resolveMimicryHints({ hints, task });
          const jobId = crypto.randomUUID();
          await this.writeArtifactJob(jobId, {
            status: "PROCESSING",
            created_at: new Date().toISOString()
          });
          await launchArtifactWorkflow(
            this.env.ARTIFACT_WORKFLOW,
            jobId,
            { jobId, referenceFile, hints, task, filename },
          );
          const structuredContent = {
            status: "PROCESSING",
            job_id: jobId
          };
          return {
            structuredContent,
            content: [
              {
                type: "text",
                text: `Rendering started. Call await_result now with job_id ${jobId}.`
              }
            ]
          };
        } catch (error) {
          const diagnostic = safeFailureDiagnostic(error);
          const message =
            error instanceof ContainerRenderError
              ? error.message
              : `${UNAVAILABLE}\nDiagnostic: ${diagnostic}`;
          return {
            isError: true,
            content: [{ type: "text", text: message }],
            _meta: {
              ...(error instanceof ContainerRenderError && error.report
                ? { "artifact-mimicry/validation-report": error.report }
                : {}),
              "artifact-mimicry/failure-diagnostic": diagnostic
            }
          };
        }
      }
    );

    this.server.registerTool(
      "await_result",
      {
        title: "Await validated Word artifact",
        description:
          "Waits for an Artifact Mimicry job. Call automatically after execute and call again if it returns PROCESSING. Never ask the user to poll.",
        inputSchema: {
          job_id: z.string().uuid()
        },
        outputSchema: {
          status: z.enum(ARTIFACT_TOOL_STATUSES),
          job_id: z.string(),
          filename: z.string().optional(),
          download_url: z.string().url().optional(),
          expires_at: z.string().optional(),
          validation: z.record(z.string(), z.boolean()).optional(),
          validation_report: z.unknown().optional(),
          message: z.string().optional(),
          diagnostic: z.string().optional(),
        },
        annotations: {
          readOnlyHint: true,
          destructiveHint: false,
          openWorldHint: true
        }
      },
      async ({ job_id: jobId }) => this.artifactJobResponse(jobId, true)
    );
  }
}

// A new Durable Object class deliberately rotates existing MCP sessions after
// a tool-contract update. OAuth clients and the public MCP URL stay unchanged.
export class ArtifactMimicryMCPV2 extends ArtifactMimicryMCP {}
export class ArtifactMimicryMCPV3 extends ArtifactMimicryMCP {}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    if (
      request.method === "GET" &&
      url.pathname === "/.well-known/openai-apps-challenge"
    ) {
      return new Response(OPENAI_APPS_CHALLENGE_TOKEN, {
        headers: {
          "content-type": "text/plain; charset=utf-8",
          "cache-control": "no-store"
        }
      });
    }
    if (request.method === "GET" && publicPages[url.pathname]) {
      return publicPages[url.pathname]();
    }
    if (request.method === "GET" && url.pathname === "/") {
      return Response.json({
        name: "artifact-mimicry",
        version: "1.0.0",
        status: "ok",
        mcp: "/mcp"
      });
    }
    if (request.method === "GET" && url.pathname.startsWith("/artifacts/")) {
      const [, , artifactId] = url.pathname.split("/");
      const store = env.ARTIFACT_STORE.get(env.ARTIFACT_STORE.idFromName("global"));
      return store.fetch(new Request(`https://artifact-store/get/${artifactId}`));
    }
    if (request.method === "GET" && url.pathname.startsWith("/jobs/")) {
      const jobId = url.pathname.slice("/jobs/".length);
      if (!isArtifactJobId(jobId) || url.pathname !== artifactJobPath(jobId)) {
        return new Response("Not Found", { status: 404 });
      }
      const store = env.ARTIFACT_STORE.get(
        env.ARTIFACT_STORE.idFromName("global"),
      );
      const jobResponse = await store.fetch(
        new Request(`https://artifact-store/job-get/${jobId}`),
      );
      if (!jobResponse.ok) return jobResponse;
      const record = await jobResponse.json();
      if (record.status !== "PROCESSING") {
        return Response.json(record, {
          headers: { "cache-control": "private, no-store" },
        });
      }
      let workflowStatus;
      try {
        workflowStatus = await (
          await env.ARTIFACT_WORKFLOW.get(jobId)
        ).status();
      } catch {
        workflowStatus = { status: "unknown" };
      }
      return Response.json(withWorkflowStatus(record, workflowStatus), {
        headers: { "cache-control": "private, no-store" },
      });
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
