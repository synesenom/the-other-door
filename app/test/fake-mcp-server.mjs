// A stand-in for `python -m door.mcp_server`: a stdio MCP server whose tools
// behave like door's (JSON in one text block, {"error"} results, ...) or
// misbehave on purpose (exit, hang). Used by door-server.test.ts.
import { appendFileSync, writeSync } from 'node:fs'
import { Server } from '@modelcontextprotocol/sdk/server/index.js'
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js'
import { ListToolsRequestSchema, CallToolRequestSchema } from '@modelcontextprotocol/sdk/types.js'

const object = { type: 'object', properties: {}, additionalProperties: true }
const tools = ['json', 'err', 'ambiguous', 'conflict', 'iserror', 'exit', 'slow', 'env', 'slow_progress'].map((name) => ({
  name,
  description: `fake ${name}`,
  inputSchema: object,
}))
const text = (value, isError = false) => ({
  content: [{ type: 'text', text: typeof value === 'string' ? value : JSON.stringify(value, null, 2) }],
  isError,
})

// One line per start, so a test can count spawns.
if (process.env.FAKE_START_LOG) appendFileSync(process.env.FAKE_START_LOG, `${process.pid}\n`)
// A child that dies at once, for the "no restart loop" test.
if (process.env.FAKE_DIE_ON_START) {
  writeSync(2, 'ModuleNotFoundError: no module named door\n')
  process.exit(3)
}

const server = new Server({ name: 'fake-door', version: '0.0.0' }, { capabilities: { tools: {} } })
server.setRequestHandler(ListToolsRequestSchema, async () => ({ tools }))
server.setRequestHandler(CallToolRequestSchema, async (req, extra) => {
  const { name, arguments: args = {} } = req.params
  switch (name) {
    case 'json':
      return text({ ok: true, args, pid: process.pid })
    case 'err':
      return text({ error: 'no such job' })
    case 'ambiguous':
      return text({ error: 'several jobs match', candidates: [{ job_id: 'a.1', title: 'T', company: 'C', status: 'unapplied' }] })
    case 'conflict':
      return text({ error: 'both changed', conflict: true })
    case 'iserror':
      return text('Error executing tool: boom', true)
    case 'exit':
      writeSync(2, 'Traceback (most recent call last):\nRuntimeError: the fake fell over\n')
      process.exit(1)
    case 'slow':
      await new Promise((r) => setTimeout(r, args.ms ?? 5000))
      return text({ slow: true })
    case 'slow_progress': {
      const token = req.params._meta?.progressToken
      if (token !== undefined) {
        for (const n of [1, 2]) {
          await extra.sendNotification({
            method: 'notifications/progress',
            params: { progressToken: token, progress: n, total: 2, message: `step ${n}` },
          })
        }
      }
      // The client dispatches notifications a tick after the response; real runs are long.
      await new Promise((r) => setTimeout(r, 100))
      return text({ done: true, withToken: token !== undefined })
    }
    case 'env':
      return text({ env: process.env })
    default:
      return text({ error: `unknown tool ${name}` })
  }
})
await server.connect(new StdioServerTransport())
