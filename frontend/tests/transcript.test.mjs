import { test } from 'node:test'
import assert from 'node:assert/strict'
import { build } from 'vite'

const output = await build({ configFile: false, logLevel: 'silent', build: {
  write: false, minify: false, lib: { entry: 'src/features/meetings/groupTranscript.ts', formats: ['es'] },
} })
const bundle = Array.isArray(output) ? output[0] : output
const { groupTranscript } = await import(`data:text/javascript;base64,${Buffer.from(bundle.output[0].code).toString('base64')}`)
const segment = (id, speaker_id, text) => ({ id: String(id), speaker_id, text, started_at_ms: id * 1000 })

test('short fragments become a complete turn with its initial timestamp', () => {
  const input = [segment(1, 'a', ' Предлагаю '), segment(2, 'a', 'запустить пилот'), segment(3, 'a', '.'), segment(4, 'a', 'Завтра.')]
  const original = structuredClone(input)
  assert.deepEqual(groupTranscript(input), [{ ...input[0], text: 'Предлагаю запустить пилот. Завтра.' }])
  assert.deepEqual(input, original)
})

test('a speaker returning after an interruption starts a new turn', () => {
  const input = [segment(1, 'a', 'Первый вопрос.'), segment(2, 'b', 'Согласен.'), segment(3, 'a', 'Следующий вопрос.')]
  assert.deepEqual(groupTranscript(input), input)
})

test('a turn crossing an API page boundary stays together', () => {
  const page1 = [segment(1, 'a', 'Подготовим')]
  const page2 = [segment(2, 'a', 'документы.'), segment(3, 'b', 'Хорошо.')]
  assert.deepEqual(groupTranscript([...page1, ...page2]).map(t => t.text), ['Подготовим документы.', 'Хорошо.'])
})

test('empty transcript and punctuation fragments are handled', () => {
  assert.deepEqual(groupTranscript([]), [])
  assert.equal(groupTranscript(['«', 'Пилот', '»', 'готов', '.'].map((text, i) => segment(i, 'a', text)))[0].text, '«Пилот» готов.')
})
