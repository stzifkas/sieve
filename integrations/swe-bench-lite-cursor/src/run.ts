/**
 * Generate SWE-bench Lite predictions JSONL using the Cursor TypeScript SDK (local agent).
 *
 * Prereqs: git, docker (for harness only), uv (for sieve hook rewrite), CURSOR_API_KEY, Node 18+.
 *
 * @example
 * cd integrations/swe-bench-lite-cursor && npm install
 * export CURSOR_API_KEY=cursor_...
 * npx tsx src/run.ts --manifest ../../benchmarks/manifests/lite_smoke.jsonl --predictions ../../artifacts/lite.cursor.jsonl --profile baseline --limit 1
 */
import { execSync } from "node:child_process";
import { createReadStream, existsSync } from "node:fs";
import { appendFile, mkdir, readdir, readFile, rm, writeFile } from "node:fs/promises";
import { createInterface } from "node:readline";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { parseArgs } from "node:util";

import { Agent, CursorAgentError } from "@cursor/sdk";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

type ManifestRow = {
  instance_id: string;
  repo: string;
  base_commit: string;
  problem_statement: string;
};

const REPO_ROOT = path.resolve(__dirname, "..", "..");

async function readExistingIds(predictionsPath: string): Promise<Set<string>> {
  const ids = new Set<string>();
  if (!existsSync(predictionsPath)) return ids;
  const text = await readFile(predictionsPath, "utf8");
  for (const line of text.split("\n")) {
    if (!line.trim()) continue;
    try {
      const o = JSON.parse(line) as { instance_id?: string };
      if (o.instance_id) ids.add(o.instance_id);
    } catch {
      /* malformed line */
    }
  }
  return ids;
}

async function* iterateManifest(manifestPath: string): AsyncGenerator<ManifestRow> {
  const input = createReadStream(manifestPath, { encoding: "utf8" });
  const rl = createInterface({ input, crlfDelay: Infinity });
  try {
    for await (const line of rl) {
      if (!line.trim()) continue;
      yield JSON.parse(line) as ManifestRow;
    }
  } finally {
    rl.close();
  }
}

function cloneRepo(repo: string, dest: string, commit: string) {
  const url = `https://github.com/${repo}.git`;
  const env = { ...process.env, GIT_TERMINAL_PROMPT: "0" };
  execSync(`git clone --quiet "${url}" "${dest}"`, { stdio: "inherit", env });
  execSync(`git -C "${dest}" checkout --quiet ${commit}`, { stdio: "inherit", env });
}

async function injectSieveHook(workspace: string, sieveRepoRoot: string) {
  const hookPy = path.join(sieveRepoRoot, ".cursor", "hooks", "sieve_pre_shell.py");
  const hooksJson = {
    version: 1,
    hooks: {
      preToolUse: [{ command: `python3 ${hookPy}`, matcher: "Shell" }],
    },
  };
  await mkdir(path.join(workspace, ".cursor"), { recursive: true });
  await writeFile(path.join(workspace, ".cursor", "hooks.json"), JSON.stringify(hooksJson, null, 2), "utf8");
}

async function stripCursorDir(workspace: string) {
  await rm(path.join(workspace, ".cursor"), { recursive: true, force: true });
}

function extractPatch(workspace: string): string {
  const env = { ...process.env, GIT_TERMINAL_PROMPT: "0" };
  execSync(`git -C "${workspace}" add -A`, { stdio: "pipe", env });
  return execSync(`git -C "${workspace}" diff --cached`, { encoding: "utf8", env });
}

function profileRoot(workspaceRoot: string, instanceId: string, profile: string): string {
  const slug = instanceId.replace(/[/\\]/g, "_");
  return path.join(workspaceRoot, slug, profile);
}

async function aggregateContext(runDir: string): Promise<{ raw_chars: number; agent_chars: number; saved_chars: number }> {
  let raw_chars = 0;
  let agent_chars = 0;
  let saved_chars = 0;
  try {
    const entries = await readdir(runDir);
    for (const entry of entries.sort()) {
      if (!entry.endsWith(".meta.json")) continue;
      const payload = JSON.parse(await readFile(path.join(runDir, entry), "utf8")) as Record<string, unknown>;
      raw_chars += Number(payload.raw_chars ?? 0);
      agent_chars += Number(payload.agent_chars ?? 0);
      saved_chars += Number(payload.saved_chars ?? 0);
    }
  } catch {
    return { raw_chars, agent_chars, saved_chars };
  }
  return { raw_chars, agent_chars, saved_chars };
}

function buildPrompt(row: ManifestRow): string {
  return [
    "You are working inside a real Git repository checkout pinned to a benchmark commit.",
    "Fix the issue below with minimal, targeted edits. Prefer tests that reproduce the bug.",
    "Do not change unrelated modules, packaging metadata, or licensing.",
    "",
    "## Problem",
    row.problem_statement,
    "",
    "Save edits to files on disk. Do not paste a full unified diff in chat.",
  ].join("\n");
}

async function appendPrediction(predictionsPath: string, record: object) {
  await appendFile(predictionsPath, JSON.stringify(record) + "\n", "utf8");
}

async function main() {
  const { values } = parseArgs({
    args: process.argv.slice(2),
    options: {
      manifest: { type: "string" },
      predictions: { type: "string" },
      "workspace-root": { type: "string" },
      "sieve-repo-root": { type: "string" },
      profile: { type: "string", default: "baseline" },
      limit: { type: "string" },
      resume: { type: "boolean", default: false },
      "keep-workspaces": { type: "boolean", default: false },
      model: { type: "string", default: "composer-2" },
    },
  });

  const apiKey = process.env.CURSOR_API_KEY;
  if (!apiKey) {
    console.error("error: set CURSOR_API_KEY");
    process.exit(1);
  }

  const manifest = values.manifest;
  const predictions = values.predictions;
  if (!manifest || !predictions) {
    console.error(
      "usage: npx tsx src/run.ts --manifest <lite.jsonl> --predictions <out.jsonl> [--profile baseline|sieve] [--limit N] [--resume]",
    );
    process.exit(2);
  }

  const profile = values.profile === "sieve" ? "sieve" : "baseline";
  const sieveRepoRoot = path.resolve(values["sieve-repo-root"] ?? REPO_ROOT);
  const workspaceRoot = path.resolve(values["workspace-root"] ?? path.join(REPO_ROOT, ".swe-workspaces"));
  await mkdir(workspaceRoot, { recursive: true });
  await mkdir(path.dirname(path.resolve(predictions)), { recursive: true });

  const limit = values.limit ? Number.parseInt(values.limit, 10) : Number.POSITIVE_INFINITY;
  if (!Number.isFinite(limit)) {
    console.error("error: --limit must be a number");
    process.exit(2);
  }

  const done = values.resume ? await readExistingIds(predictions) : new Set<string>();

  let completed = 0;
  for await (const row of iterateManifest(path.resolve(manifest))) {
    if (done.has(row.instance_id)) {
      console.error("skip (resume)", row.instance_id);
      continue;
    }
    if (completed >= limit) break;

    const workProfileRoot = profileRoot(workspaceRoot, row.instance_id, profile);
    const workDir = path.join(workProfileRoot, "workspace");
    const runDir = path.join(workProfileRoot, ".sieve", "runs");
    const sessionFile = path.join(workProfileRoot, ".sieve", "session.json");
    const artifactDir = path.join(path.dirname(path.resolve(predictions)), "swe-bench-lite-runs", row.instance_id.replace(/[/\\]/g, "_"), profile);
    await rm(workProfileRoot, { recursive: true, force: true }).catch(() => {});
    await mkdir(workDir, { recursive: true });
    await mkdir(runDir, { recursive: true });
    await mkdir(artifactDir, { recursive: true });
    console.error("===", row.instance_id, workDir, "profile=", profile, "===");

    try {
      cloneRepo(row.repo, workDir, row.base_commit);
      await injectSieveHook(workDir, sieveRepoRoot);

      const prompt = buildPrompt(row);
      let runResult;
      const priorEnv = {
        SIEVE_NO_SIEVE: process.env.SIEVE_NO_SIEVE,
        SIEVE_SAVE_RAW: process.env.SIEVE_SAVE_RAW,
        SIEVE_SAVE_RAW_DIR: process.env.SIEVE_SAVE_RAW_DIR,
        SIEVE_SESSION_FILE: process.env.SIEVE_SESSION_FILE,
      };
      process.env.SIEVE_NO_SIEVE = profile === "baseline" ? "1" : "0";
      process.env.SIEVE_SAVE_RAW = "1";
      process.env.SIEVE_SAVE_RAW_DIR = runDir;
      process.env.SIEVE_SESSION_FILE = sessionFile;
      try {
        runResult = await Agent.prompt(prompt, {
          apiKey,
          model: { id: values.model ?? "composer-2" },
          local: { cwd: workDir },
        });
      } catch (e) {
        process.env.SIEVE_NO_SIEVE = priorEnv.SIEVE_NO_SIEVE;
        process.env.SIEVE_SAVE_RAW = priorEnv.SIEVE_SAVE_RAW;
        process.env.SIEVE_SAVE_RAW_DIR = priorEnv.SIEVE_SAVE_RAW_DIR;
        process.env.SIEVE_SESSION_FILE = priorEnv.SIEVE_SESSION_FILE;
        if (e instanceof CursorAgentError) {
          console.error("CursorAgentError", row.instance_id, e.message);
          await appendPrediction(predictions, {
            instance_id: row.instance_id,
            model_name_or_path: `cursor-sdk-${profile}-startup-fail`,
            model_patch: "",
            profile,
            has_patch: false,
            resolved: false,
          });
          completed++;
          continue;
        }
        throw e;
      }
      process.env.SIEVE_NO_SIEVE = priorEnv.SIEVE_NO_SIEVE;
      process.env.SIEVE_SAVE_RAW = priorEnv.SIEVE_SAVE_RAW;
      process.env.SIEVE_SAVE_RAW_DIR = priorEnv.SIEVE_SAVE_RAW_DIR;
      process.env.SIEVE_SESSION_FILE = priorEnv.SIEVE_SESSION_FILE;

      if (runResult.status !== "finished") {
        console.error("run ended with status", row.instance_id, runResult.status);
        await appendPrediction(predictions, {
          instance_id: row.instance_id,
          model_name_or_path: `cursor-sdk-${profile}-${runResult.status}`,
          model_patch: "",
          profile,
          has_patch: false,
          resolved: false,
        });
        completed++;
        continue;
      }

      await stripCursorDir(workDir);
      const patch = extractPatch(workDir);
      const context = await aggregateContext(runDir);
      await writeFile(path.join(artifactDir, "model.patch"), patch, "utf8");
      await appendPrediction(predictions, {
        instance_id: row.instance_id,
        model_name_or_path: `cursor-sdk-${profile}`,
        model_patch: patch,
        profile,
        has_patch: Boolean(patch.trim()),
        resolved: false,
        workspace: workDir,
        context,
        artifacts: {
          patch_path: path.join(artifactDir, "model.patch"),
          run_dir: runDir,
          session_file: sessionFile,
        },
      });
      console.error("patch chars", row.instance_id, patch.length);
    } catch (err) {
      console.error("instance error", row.instance_id, err);
      await appendPrediction(predictions, {
        instance_id: row.instance_id,
        model_name_or_path: `cursor-sdk-${profile}-error`,
        model_patch: "",
        profile,
        has_patch: false,
        resolved: false,
      });
    } finally {
      if (!values["keep-workspaces"]) {
        await rm(workProfileRoot, { recursive: true, force: true }).catch(() => {});
      }
    }
    completed++;
  }

  console.error("finished; predictions ->", predictions);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
