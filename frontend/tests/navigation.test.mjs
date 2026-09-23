import { test } from 'node:test'
import assert from 'node:assert/strict'
import { build } from 'vite'

const output = await build({ configFile: false, logLevel: 'silent', build: {
  write: false, minify: false, lib: { entry: 'src/lib/navigation.ts', formats: ['es'] },
} })
const bundle = Array.isArray(output) ? output[0] : output
const { parseRoute, routeHash } = await import(`data:text/javascript;base64,${Buffer.from(bundle.output[0].code).toString('base64')}`)

test('meeting deep links survive reload and cannot switch a real recording to demo', () => {
  const route = { view: 'meeting', meetingId: 'a731897d-c1e8-4403-8e79-5385185daf66', demo: false }
  assert.deepEqual(parseRoute(routeHash(route)), route)
  assert.deepEqual(parseRoute(routeHash(route) + '?demo=1'), route)
})
test('invalid routes fall back safely and notifications always show real data', () => {
  assert.equal(parseRoute('#/unknown').view, 'dashboard')
  assert.equal(parseRoute('#/meeting/not-an-id').meetingId, null)
  assert.equal(parseRoute('#/notifications?demo=1').demo, false)
  assert.equal(parseRoute('#/tasks?demo=1').demo, true)
})
