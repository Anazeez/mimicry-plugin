import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("deployment config stays beside wrangler.jsonc so relative entry paths resolve", async () => {
  const workflow = await readFile(
    new URL("../../.github/workflows/deploy-mcp.yml", import.meta.url),
    "utf8",
  );

  assert.match(workflow, /deploy\.wrangler\.jsonc/);
  assert.doesNotMatch(workflow, /\.wrangler\/deploy\.jsonc/);
});

test("LibreOffice renderer has production memory and CPU headroom", async () => {
  const config = JSON.parse(
    await readFile(new URL("../wrangler.jsonc", import.meta.url), "utf8"),
  );
  assert.equal(config.containers[0].instance_type, "standard-1");
  assert.equal(config.containers[0].max_instances, 1);
});
