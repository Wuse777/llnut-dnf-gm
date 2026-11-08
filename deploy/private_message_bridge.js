/* Opt-in fragment for the fingerprinted 1031 df_game_r Frida script.
 * Defining this module performs no hooks, sockets, scheduling or native calls.
 * Activation belongs in the existing start() during a planned game restart.
 * Socket API: https://frida.re/docs/javascript-api/#socket
 */
var DnfGmPrivateMessage = (function () {
  'use strict';
  var VERSION = 1;
  var GAME = '8859c99d8290dc5fb58151444138cf2697b2bfff12d47d6159596a03f20b5261';
  var PATH = '/data/.dnfgm-private-message.sock';
  var runtime = null;
  function exact(value, keys) {
    return value !== null && typeof value === 'object' && !Array.isArray(value) &&
      Object.keys(value).sort().join(',') === keys.slice().sort().join(',');
  }
  function utf8(value) {
    var encoded = encodeURIComponent(value), bytes = [];
    for (var i = 0; i < encoded.length; i++) {
      if (encoded[i] === '%') { bytes.push(parseInt(encoded.slice(i + 1, i + 3), 16)); i += 2; }
      else bytes.push(encoded.charCodeAt(i));
    }
    return new Uint8Array(bytes);
  }
  function decode(bytes) {
    return decodeURIComponent(Array.prototype.map.call(bytes, function (v) {
      return '%' + ('0' + v.toString(16)).slice(-2);
    }).join(''));
  }
  function validText(value) {
    // Cf/Cc are rejected by the Python boundary as well. This second boundary
    // accepts a conservative character set and rejects UTF-16 surrogates.
    if (typeof value !== 'string' || !value.trim() || /[\x00-\x1f\x7f-\x9f\u00ad\u061c\u200b-\u200f\u2028-\u202e\u2060-\u206f\ufeff]/.test(value)) return false;
    try { return utf8(value).length <= 254; } catch (_) { return false; }
  }
  function createHandler(options) {
    var active = true, pending = 0, seen = new Map();
    var now = options.now || function () { return Date.now() / 1000; };
    function result(op, status, reason) {
      return { operation_id: op, transport_status: status, reason_code: reason };
    }
    async function handle(request) {
      if (!active || !request || request.token !== options.token) throw new Error('Unauthorized bridge request');
      if (exact(request, ['action', 'token']) && request.action === 'status') {
        return { ready: true, bridge_version: VERSION, game_sha256: GAME };
      }
      if (!exact(request, ['action', 'token', 'operation_id', 'uid', 'charac_no', 'message', 'expires_at']) ||
          request.action !== 'send' || typeof request.operation_id !== 'string' || !/^[a-f0-9]{32}$/.test(request.operation_id) ||
          ![request.uid, request.charac_no].every(function (n) { return Number.isInteger(n) && n > 0 && n <= 0x7fffffff; }) ||
          !validText(request.message) || typeof request.expires_at !== 'number' || !Number.isFinite(request.expires_at)) {
        throw new Error('Invalid typed bridge request');
      }
      var op = request.operation_id, at = now();
      if (request.expires_at <= at || request.expires_at > at + 2) return result(op, 'not_sent', 'expired');
      seen.forEach(function (until, key) { if (until < at) seen.delete(key); });
      if (seen.has(op)) return result(op, 'not_sent', 'duplicate_operation');
      if (pending >= 1 || seen.size >= 1024) return result(op, 'not_sent', 'busy');
      seen.set(op, request.expires_at + 2);
      pending++;
      return new Promise(function (resolve) {
        var done = false;
        function finish(status, reason) {
          if (done) return;
          done = true; pending--;
          clearTimeout(timer);
          resolve(result(op, status, reason));
        }
        var timer = setTimeout(function () { finish('not_sent', 'expired'); }, 1100);
        try {
          options.schedule(function () {
            if (done) return;
            if (!active || now() >= request.expires_at) return finish('not_sent', 'expired');
            try {
              // The pointer is looked up, checked and used on the game thread.
              // Never retain CUser pointers across a scheduler/await boundary.
              var user = options.lookup(request.uid);
              if (options.isNull(user) || options.uid(user) !== request.uid || options.state(user) < 3) return finish('not_sent', 'target_offline');
              if (options.character(user) !== request.charac_no) return finish('not_sent', 'character_changed');
              options.notify(user, request.message);
              finish('sent', 'primitive_invoked');
            } catch (_) {
              // Native exceptions may occur after the effect. Never replay.
              finish('uncertain', 'primitive_failed');
            }
          });
        } catch (_) { finish('not_sent', 'busy'); }
      });
    }
    return { handle: handle, stop: function () { active = false; } };
  }
  async function start(options) {
    if (runtime) throw new Error('Bridge already active');
    if (!exact(options, ['token']) || !/^[a-f0-9]{64}$/.test(options.token)) throw new Error('Private bridge token required');
    var mainModule = Process.mainModule || Process.enumerateModules()[0];
    if (Process.platform !== 'linux' || Process.arch !== 'ia32' || !mainModule || mainModule.name !== 'df_game_r' ||
        typeof api_scheduleOnMainThread !== 'function') throw new Error('Unsupported native runtime');
    var getUser = new NativeFunction(ptr(0x84bb9cf), 'pointer', ['uint'], { abi: 'sysv' });
    var getUID = new NativeFunction(ptr(0x80c8c96), 'uint', ['pointer'], { abi: 'sysv' });
    var getState = new NativeFunction(ptr(0x80da38c), 'int', ['pointer'], { abi: 'sysv' });
    var getCharacter = new NativeFunction(ptr(0x80cbc4e), 'int', ['pointer'], { abi: 'sysv' });
    var notify = new NativeFunction(ptr(0x86886ce), 'int', ['pointer', 'pointer', 'int'], { abi: 'sysv' });
    var chmodAddress = typeof Module.getGlobalExportByName === 'function' ? Module.getGlobalExportByName('chmod') : Module.getExportByName(null, 'chmod');
    var chmod = new NativeFunction(chmodAddress, 'int', ['pointer', 'int']);
    var handler = createHandler({ token: options.token,
      schedule: function (f) { api_scheduleOnMainThread(f, []); },
      lookup: getUser, isNull: function (p) { return p.isNull(); }, uid: getUID,
      state: getState, character: getCharacter,
      notify: function (p, text) { notify(p, Memory.allocUtf8String(text), 2); }
    });
    var listener = await Socket.listen({ family: 'unix', path: PATH });
    if (chmod(Memory.allocUtf8String(PATH), 0x180) !== 0) { listener.close(); handler.stop(); throw new Error('Private socket mode required'); }
    var connections = new Set();
    runtime = { listener: listener, handler: handler, connections: connections };
    async function serve(connection) {
      if (connections.size >= 2) { await connection.close(); return; }
      connections.add(connection);
      var timer = setTimeout(function () { connection.close().catch(function () {}); }, 1600);
      try {
        var bytes = [], complete = false;
        while (!complete && bytes.length <= 4096) {
          var chunk = new Uint8Array(await connection.input.read(1024));
          if (!chunk.length) throw new Error('Incomplete frame');
          for (var i = 0; i < chunk.length; i++) {
            if (complete || bytes.length >= 4096) throw new Error('Oversized frame');
            bytes.push(chunk[i]); if (chunk[i] === 10) complete = true;
          }
        }
        var response = await handler.handle(JSON.parse(decode(new Uint8Array(bytes))));
        await connection.output.writeAll(utf8(JSON.stringify(response) + '\n').buffer);
      } catch (_) { /* No secret, user text or native error logging. */ }
      finally { clearTimeout(timer); connections.delete(connection); await connection.close(); }
    }
    (async function () {
      try {
        while (runtime && runtime.listener === listener) serve(await listener.accept()).catch(function () {});
      } catch (_) { handler.stop(); }
    })();
    return { bridge_version: VERSION };
  }
  function stop() {
    if (!runtime) return;
    var current = runtime; runtime = null;
    current.handler.stop(); current.listener.close();
    current.connections.forEach(function (connection) { connection.close(); });
  }
  return { start: start, stop: stop, createHandler: createHandler };
})();
if (typeof module !== 'undefined' && module.exports) module.exports = DnfGmPrivateMessage;
