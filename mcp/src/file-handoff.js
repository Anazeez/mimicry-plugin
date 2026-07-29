import { z } from "zod";

export const referenceFileSchema = z
  .object({
    download_url: z.string().url(),
    file_id: z.string().min(1),
    mime_type: z.string().nullable().optional(),
    file_name: z.string().nullable().optional(),
  })
  .describe(
    "Canonical ChatGPT file reference for the visual source. The host rewrites the attached file into this payload.",
  );

export const EXECUTE_TOOL_META = Object.freeze({
  "openai/fileParams": Object.freeze(["reference_file"]),
  "openai/fileUploadConfig": Object.freeze({
    store_in_library: false,
  }),
});
