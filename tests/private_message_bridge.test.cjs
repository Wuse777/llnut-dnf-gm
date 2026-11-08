const { test } = require('node:test');
const assert = require('node:assert/strict');
const bridge = require('../deploy/private_message_bridge.js');
function fixture() {
  const queued = [], calls = [];
  let at = 100;
  const user = { uid: 900001, character: 900001, state: 3 };
  const handler = bridge.createHandler({ token: 'b'.repeat(64), now: () => at,
    schedule: f => queued.push(f), lookup: uid => user, isNull: p => p === null,
    uid: p => p.uid, character: p => p.character, state: p => p.state,
    notify: (p, text) => calls.push({ uid: p.uid, text }) });
  const request = { action: 'send', token: 'b'.repeat(64), operation_id: 'a'.repeat(32),
    uid: 900001, charac_no: 900001, message: '系统消息', expires_at: 101 };
  return { handler, queued, calls, request, user, advance: () => { at = 102; } };
}
test('module loading is inert; notification only runs on scheduled game thread', async () => {
  const f = fixture(); const pending = f.handler.handle(f.request);
  assert.equal(f.calls.length, 0); assert.equal(f.queued.length, 1);
  f.queued.shift()();
  assert.deepEqual(await pending, { operation_id: f.request.operation_id, transport_status: 'sent', reason_code: 'primitive_invoked' });
  assert.equal(f.calls.length, 1);
  assert.equal((await f.handler.handle(f.request)).reason_code, 'duplicate_operation');
  assert.equal(f.calls.length, 1);
});
test('rechecks fresh identity and current character at execution', async () => {
  for (const field of ['uid', 'character', 'state']) {
    const f = fixture(); const pending = f.handler.handle(f.request);
    f.user[field] = 0; f.queued.shift()();
    assert.equal((await pending).transport_status, 'not_sent'); assert.equal(f.calls.length, 0);
  }
});
test('expired or disposed queued work cannot send later', async () => {
  for (const stop of [false, true]) {
    const f = fixture(); const pending = f.handler.handle(f.request);
    if (stop) f.handler.stop(); else f.advance();
    f.queued.shift()(); assert.equal((await pending).reason_code, 'expired'); assert.equal(f.calls.length, 0);
  }
});
test('strict schema, token, byte bounds and no caller opcode or sender', async () => {
  for (const mutation of [{ token: 'bad' }, { message: '汉'.repeat(85) }, { message: '\n' },
    { opcode: 1 }, { sender_uid: 3 }, { uid: true }, { charac_no: 0 }]) {
    const f = fixture(); await assert.rejects(f.handler.handle({ ...f.request, ...mutation }));
    assert.equal(f.queued.length, 0);
  }
});
test('exception after entering primitive remains uncertain and cannot replay', async () => {
  const f = fixture();
  const handler = bridge.createHandler({ token: f.request.token, now: () => 100,
    schedule: cb => f.queued.push(cb), lookup: () => f.user, isNull: () => false,
    uid: p => p.uid, character: p => p.character, state: p => p.state,
    notify: () => { f.calls.push(1); throw Error('synthetic'); } });
  const pending = handler.handle(f.request); f.queued.shift()();
  assert.equal((await pending).transport_status, 'uncertain');
  assert.equal((await handler.handle(f.request)).reason_code, 'duplicate_operation'); assert.equal(f.calls.length, 1);
});
