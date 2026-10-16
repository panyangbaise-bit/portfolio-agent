// Real MCP stdio -> downloaded bridge -> A2A HTTP smoke test.
// Run after install-a2a-mcp.py; --ask also invokes the configured LLM.
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { homedir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { randomUUID } from "node:crypto";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const install = join(homedir(), ".local/share/portfolio-agent-a2a");
const require = createRequire(join(install, "package.json"));
const { Client } = await import(pathToFileURL(require.resolve("@modelcontextprotocol/sdk/client/index.js")));
const { StdioClientTransport } = await import(pathToFileURL(require.resolve("@modelcontextprotocol/sdk/client/stdio.js")));
const client = new Client({ name: "portfolio-integration-test", version: "1.0.0" });
const transport = new StdioClientTransport({
  command: join(root, ".venv/bin/python"),
  args: [join(root, "deploy/run-a2a-mcp.py"), "--config", join(homedir(), ".config/portfolio-agent/a2a-mcp.json"),
    "--node", process.execPath, "--bridge", join(install, "node_modules/@cognicellai/a2a-mcp/dist/index.js")],
  stderr: "pipe",
});

async function call(name, request = {}) {
  const reply = await client.callTool({ name, arguments: name === "a2a_list_agents" ? {} : { agent: "portfolio", request } });
  assert(!reply.isError, `${name}: ${JSON.stringify(reply.content)}`);
  return reply.structuredContent?.result ?? JSON.parse(reply.content[0].text);
}
async function send(parts, contextId) {
  const result = await call("a2a_send_message", {
    message: { messageId: randomUUID(), role: "ROLE_USER", parts, ...(contextId ? {contextId} : {}) },
    configuration: { returnImmediately: true },
  });
  let task = result.task ?? result;
  assert(task?.id, `Expected A2A task; result keys: ${Object.keys(result)}, value keys: ${Object.keys(result.value ?? {})}`);
  const deadline = Date.now() + 240000;
  while (["TASK_STATE_WORKING", "TASK_STATE_SUBMITTED", 1, 2].includes(task.status.state)) {
    assert(Date.now() < deadline, `Task ${task.id} did not finish within 240 seconds`);
    await new Promise(resolve => setTimeout(resolve, 1000));
    task = await call("a2a_get_task", { id: task.id });
  }
  assert(["TASK_STATE_COMPLETED", 3].includes(task.status.state), `Task ${task.id} failed`);
  return task;
}

try {
  await client.connect(transport);
  const tools = await client.listTools();
  assert(tools.tools.some(t => t.name === "a2a_send_message"));
  await call("a2a_list_agents");
  const card = await call("a2a_get_agent_card");
  assert(card.name === "Portfolio Agent");
  console.log("PASS MCP initialize, tool discovery, agent discovery and bearer-authenticated connection");
  for (const operation of ["holdings", "transactions"]) {
    const task = await send([{ data: { operation, filters: { limit: 1 } } }]);
    const part = task.artifacts[0].parts[0];
    const data = part.data ?? part.content?.value;
    assert(data.source === "portfolio_ledger" && data.operation === operation);
    assert(Array.isArray(data.items));
    assert(data.items.length <= 1);
    if (data.next_offset !== null) {
      const next = await send([{ data: { operation, filters: { limit: 1, offset: data.next_offset } } }]);
      const nextPart = next.artifacts[0].parts[0];
      assert((nextPart.data ?? nextPart.content?.value).offset === data.next_offset);
    }
    console.log(`PASS A2A ${operation}, structured output, task polling and pagination`);
  }
  if (process.argv.includes("--ask")) {
    console.log("RUN real portfolio-agent analysis through MCP/A2A");
    const task = await send([{text: "请仅调用 query_portfolio_ledger 查询当前未平仓持仓总数。只回复总数和数据来源，不查行情或新闻，不执行任何修改。"}]);
    assert(task.artifacts[0].parts.some(p => typeof (p.text ?? p.content?.value) === "string" && (p.text ?? p.content?.value).length > 0));
    console.log("PASS real LLM/tool answer through MCP/A2A (portfolio values omitted from test log)");
  }
} finally {
  await client.close();
}
