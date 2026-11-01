import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';

async function worker() {
  const handlers = {}, cached = [], fetched = [];
  const context = {
    URL, Promise,
    self: {location: {origin: 'https://reader.example'}, addEventListener: (type, fn) => handlers[type] = fn,
      clients: {claim: async () => {}}, skipWaiting: async () => {}},
    caches: {open: async () => ({put: async (path) => cached.push(path)}), keys: async () => [],
      match: async () => null, delete: async () => true},
    fetch: async input => {fetched.push(input); return {ok: true, redirected: true, headers: {get: () => null}};},
  };
  vm.runInNewContext(await readFile(new URL('../app/static/sw.js', import.meta.url), 'utf8'), context);
  return {handlers, cached, fetched};
}

test('service worker never intercepts API requests, external URLs, or POSTs', async () => {
  const {handlers} = await worker();
  for (const request of [
    {url: 'https://reader.example/api/folders', method: 'GET', mode: 'cors'},
    {url: 'https://reader.example/api/convert', method: 'POST'},
    {url: 'https://other.example/app.js', method: 'GET'},
    {url: 'https://reader.example/app.js?secret=1', method: 'GET'},
  ]) {
    let intercepted = false;
    handlers.fetch({request, respondWith: () => {intercepted = true;}});
    assert.equal(intercepted, false);
  }
});

test('installation refuses authentication redirects instead of caching them', async () => {
  const {handlers, cached} = await worker();
  let installed;
  handlers.install({waitUntil: promise => installed = promise});
  await assert.rejects(installed);
  assert.deepEqual(cached, []);
});

test('installation metadata is fetched fresh with the browser credentials', async () => {
  const {handlers} = await worker();
  for (const path of ['/manifest.webmanifest', '/icon-192.png', '/icon-512.png']) {
    let intercepted = false;
    handlers.fetch({
      request: {url: 'https://reader.example' + path, method: 'GET'},
      respondWith: () => {intercepted = true;},
    });
    assert.equal(intercepted, false, path + ' must bypass the shell cache');
  }
});
