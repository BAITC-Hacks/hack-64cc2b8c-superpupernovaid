import { test, after } from 'node:test'
import assert from 'node:assert/strict'
import { build } from 'vite'

// Bundle the actual browser client so its Vite environment matches production.
const output = await build({ configFile: false, logLevel: 'silent', build: {
  write: false, minify: false, lib: { entry: 'src/features/meetings/liveApi.ts', formats: ['es'] },
} })
const bundle = Array.isArray(output) ? output[0] : output
const { liveApi } = await import(`data:text/javascript;base64,${Buffer.from(bundle.output[0].code).toString('base64')}`)
const originalFetch = globalThis.fetch
after(() => { globalThis.fetch = originalFetch })
const response = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

test('meeting list follows and encodes cursors without dropping records', async () => {
  const calls = []
  globalThis.fetch = async url => {
    calls.push(url)
    return calls.length === 1 ? response({ items: [{ id: 'a' }], next_cursor: 'a+/=' }) : response({ items: [{ id: 'b' }], next_cursor: null })
  }
  assert.deepEqual(await liveApi.meetings(), [{ id: 'a' }, { id: 'b' }])
  assert.deepEqual(calls, ['/api/v1/meetings?limit=100', '/api/v1/meetings?limit=100&cursor=a%2B%2F%3D'])
})

test('an error on a later page rejects the incomplete list', async () => {
  let calls = 0
  globalThis.fetch = async () => ++calls === 1 ? response({ items: [{ id: 'a' }], next_cursor: 'next' }) : response({ detail: 'Unavailable' }, 503)
  await assert.rejects(liveApi.tasks(), /Unavailable/)
})

test('task status is persisted with PATCH and server response is authoritative', async () => {
  globalThis.fetch = async (url, init) => {
    assert.equal(url, '/api/v1/tasks/task-id')
    assert.equal(init.method, 'PATCH')
    assert.deepEqual(JSON.parse(init.body), { status: 'in_progress' })
    return response({ id: 'task-id', status: 'overdue' })
  }
  assert.equal((await liveApi.task('task-id', { status: 'in_progress' })).status, 'overdue')
})

test('transcript search and page cursor are encoded independently', async () => {
  globalThis.fetch = async url => {
    const parsed = new URL(url, 'http://localhost')
    assert.equal(parsed.searchParams.get('q'), 'срок & план')
    assert.equal(parsed.searchParams.get('cursor'), 'a+/=')
    return response({ items: [], next_cursor: null })
  }
  await liveApi.transcript('meeting-id', 'срок & план', 'a+/=')
})

test('structured backend errors and validation messages reach the UI', async () => {
  globalThis.fetch = async () => response({ detail: { code: 'speech_disabled', message: 'Speech disabled' } }, 503)
  await assert.rejects(liveApi.speech('meeting-id', 'media-id'), /Speech disabled/)
  globalThis.fetch = async () => response({ detail: [{ msg: 'Invalid date' }] }, 422)
  await assert.rejects(liveApi.createTask('meeting-id', {}), /Invalid date/)
})

test('background processing submits the current media and both export formats', async () => {
  globalThis.fetch = async (url, init) => {
    assert.equal(url, '/api/v1/meetings/meeting-id/process')
    assert.equal(init.method, 'POST')
    assert.deepEqual(JSON.parse(init.body), { media_id: 'media-id', export_formats: ['docx', 'pdf'] })
    return response({ id: 'run-id', status: 'queued' }, 202)
  }
  assert.equal((await liveApi.process('meeting-id', 'media-id')).status, 'queued')
})

test('missing run is normal but other API failures are not swallowed', async () => {
  globalThis.fetch = async () => response({ detail: { code: 'processing_input_not_found' } }, 404)
  assert.equal(await liveApi.processingRun('meeting-id'), null)
  globalThis.fetch = async () => response({ detail: 'Database unavailable' }, 503)
  await assert.rejects(liveApi.processingRun('meeting-id'), /Database unavailable/)
})

test('PDF and DOCX downloads preserve binary bytes and use the correct endpoint', async () => {
  const bytes = new Uint8Array([0, 255, 80, 75, 3, 4])
  for (const format of ['pdf', 'docx']) {
    globalThis.fetch = async url => {
      assert.equal(url, `/api/v1/meetings/meeting-id/exports/${format}`)
      return new Response(bytes, { headers: { 'Content-Type': format === 'pdf' ? 'application/pdf' : 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' } })
    }
    const file = await liveApi.exportFile('meeting-id', format)
    assert.deepEqual(new Uint8Array(await file.blob.arrayBuffer()), bytes)
    assert.equal(file.filename, `meeting_meeting-id_protocol.${format}`)
  }
})

test('export errors retain status/code and unexpected HTML is not downloaded', async () => {
  globalThis.fetch = async () => response({ detail: { code: 'meeting_protocol_not_ready', message: 'Not ready' } }, 409)
  await assert.rejects(liveApi.exportFile('meeting-id', 'pdf'), error => error.status === 409 && error.code === 'meeting_protocol_not_ready')
  globalThis.fetch = async () => new Response('<html>Proxy error</html>', { headers: { 'Content-Type': 'text/html' } })
  await assert.rejects(liveApi.exportFile('meeting-id', 'pdf'), /формат/)
})

test('historical export targets the immutable version', async () => {
  globalThis.fetch = async url => {
    assert.equal(url, '/api/v1/meetings/m/protocol-versions/v/exports/pdf')
    return new Response('%PDF-test', { headers: { 'Content-Type': 'application/pdf' } })
  }
  assert.equal((await liveApi.exportFile('m', 'pdf', 'v')).filename, 'meeting_m_v.pdf')
})

test('history and notifications use offset pagination and their different response contracts', async () => {
  globalThis.fetch = async url => {
    assert.equal(url, '/api/v1/meetings/m/protocol-versions?limit=50&offset=50')
    return response([{ id: 'v' }])
  }
  assert.deepEqual(await liveApi.versions('m', 50), [{ id: 'v' }])
  globalThis.fetch = async url => {
    assert.equal(url, '/api/v1/notifications?limit=50&offset=100&status=pending')
    return response({ items: [{ id: 'n' }] })
  }
  assert.deepEqual(await liveApi.notifications('pending', 100), { items: [{ id: 'n' }] })
})
