/**
 * episteme — OpenCode V2 plugin.
 *
 * Installed by `episteme sync` to ~/.config/opencode/plugins/episteme.ts.
 * Edit THIS template, not the installed copy.
 *
 * Three bridges to the Python hooks, so the gate has one implementation:
 *
 *   session.hook("context")      -> session_context.py  (once per session)
 *   tool.hook("execute.before")  -> block_dangerous.py, reasoning_surface_guard.py
 *   tool.hook("execute.after")   -> calibration_telemetry.py
 *
 * Blocking uses a throw from execute.before: OpenCode types that hook's
 * failure as Tool.Error, which surfaces to the model as the tool's error,
 * carrying the hook's stderr through unchanged.
 *
 * shortcut: the Python and hooks paths are baked in at sync time, so moving
 * the checkout requires another `episteme sync`. Bake a resolver instead if
 * the checkout ever moves often enough to bite.
 */

import { spawn } from "node:child_process"

const PYTHON = "__EPISTEME_PYTHON__"
const HOOKS = "__EPISTEME_HOOKS__"

/** OpenCode tool id -> the tool name the hooks classify against. */
const TOOL_NAMES: Record<string, string> = {
  shell: "Bash",
  bash: "Bash",
  write: "Write",
  edit: "Edit",
  multiedit: "MultiEdit",
  patch: "Edit",
}

/**
 * Give the hooks the key they look for. OpenCode names the target `path`
 * in some builds and `filePath` in others; the hooks read `file_path`
 * first and `path` second, so filling `file_path` covers both.
 */
function normaliseArgs(input: unknown): Record<string, unknown> {
  const args = (input ?? {}) as Record<string, unknown>
  const file = args.file_path ?? args.filePath ?? args.path
  return typeof file === "string" ? { ...args, file_path: file } : args
}

/** Claude-shaped PreToolUse payload, or null for tools the gate ignores. */
function payload(
  tool: string | undefined,
  sessionID: string | undefined,
  input: unknown,
  cwd: string,
): Record<string, unknown> | null {
  const name = tool ? TOOL_NAMES[tool] : undefined
  if (!name) return null
  return {
    session_id: sessionID ?? "",
    hook_event_name: "PreToolUse",
    tool_name: name,
    tool_input: normaliseArgs(input),
    cwd,
  }
}

function run(
  script: string,
  input: unknown,
  cwd: string,
): Promise<{ code: number; stdout: string; stderr: string }> {
  return new Promise((resolve) => {
    const child = spawn(PYTHON, [`${HOOKS}/${script}`], {
      cwd,
      stdio: ["pipe", "pipe", "pipe"],
    })
    let stdout = ""
    let stderr = ""
    child.stdout.on("data", (chunk) => (stdout += String(chunk)))
    child.stderr.on("data", (chunk) => (stderr += String(chunk)))
    child.on("error", (error) => resolve({ code: 1, stdout, stderr: `${stderr}${error}` }))
    child.on("close", (code) => resolve({ code: code ?? 1, stdout, stderr }))
    child.stdin.end(JSON.stringify(input))
  })
}

async function setup(ctx: any) {
  const cwd: string = ctx.location?.directory ?? process.cwd()
  const seen = new Set<string>()

  await ctx.session.hook("context", async (event: any) => {
    if (!event?.sessionID || !Array.isArray(event.system)) return
    if (seen.has(event.sessionID)) return
    seen.add(event.sessionID)
    const result = await run(
      "session_context.py",
      { session_id: event.sessionID, hook_event_name: "SessionStart", cwd },
      cwd,
    )
    if (result.code === 0 && result.stdout.trim()) {
      event.system.push({ type: "text", text: result.stdout.trim() })
    }
  })

  await ctx.tool.hook("execute.before", async (event: any) => {
    const body = payload(event?.tool, event?.sessionID, event?.input, cwd)
    if (!body) return
    for (const script of ["block_dangerous.py", "reasoning_surface_guard.py"]) {
      const result = await run(script, body, cwd)
      if (result.code === 2) {
        throw new Error(result.stderr.trim() || `episteme: ${script} blocked this call`)
      }
    }
  })

  await ctx.tool.hook("execute.after", async (event: any) => {
    if (event?.status !== "completed") return
    const body = payload(event?.tool, event?.sessionID, event?.input, cwd)
    if (!body) return
    await run("calibration_telemetry.py", body, cwd)
  })
}

// Local plugin files are loaded through their default export; a named
// `id`/`setup` pair is listed but never instantiated.
export default { id: "episteme", setup }
