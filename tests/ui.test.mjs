import test from 'node:test';
import assert from 'node:assert/strict';

class Element {
  value = ''; hidden = false; disabled = false; textContent = ''; dataset = {};
  listeners = {}; selectedOptions = [{textContent: '/Reading'}];
  addEventListener(name, callback) { this.listeners[name] = callback; }
  replaceChildren(...children) { this.children = children; }
  click() { this.clicked = true; }
}

test('upload failure retains the converted file as a downloadable browser blob', async () => {
  const nodes = new Map();
  const element = id => {
    if (!nodes.has(id)) nodes.set(id, new Element());
    return nodes.get(id);
  };
  const requests = [];
  globalThis.document = {getElementById: element, createElement: () => new Element()};
  globalThis.window = {addEventListener() {}};
  globalThis.location = {search: '?url=https://example.org/story'};
  globalThis.history = {replaceState() {}};
  globalThis.localStorage = {getItem: () => null, setItem() {}};
  Object.defineProperty(globalThis, 'navigator', {configurable: true, value: {}});
  globalThis.fetch = async (path, options) => {
    requests.push({path, options});
    if (path === '/api/config') return Response.json({base_url: 'https://reader.example'});
    if (path === '/api/folders') return Response.json({folders: [{id: '', path: '/'}]});
    if (path === '/api/convert') return new Response('%PDF-original', {headers: {
      'Content-Type': 'application/pdf', 'Content-Disposition': 'attachment; filename="Garden.pdf"',
    }});
    if (path === '/api/send') return Response.json({error: {message: 'Cloud unavailable'}}, {status: 502});
    throw Error(`Unexpected request: ${path}`);
  };
  await import('../app/static/app.js');
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(element('url').value, 'https://example.org/story');
  await element('article-form').listeners.submit({preventDefault() {}});
  assert.equal(element('download').hidden, false);
  assert.equal(element('download').download, 'Garden.pdf');
  assert.ok(element('download').href.startsWith('blob:'));
  assert.match(element('status').textContent, /Cloud unavailable.*ready to download/);
  assert.equal(element('submit').disabled, false);
  const upload = requests.find(r => r.path === '/api/send');
  assert.equal(await upload.options.body.get('file').text(), '%PDF-original');
  assert.equal(upload.options.headers['X-Requested-With'], 'SendToRemarkable');
  assert.equal(upload.options.cache, 'no-store');
  URL.revokeObjectURL(element('download').href);
});

test('a proxy login page is never presented as a converted document', async () => {
  document.getElementById('delivery').value = 'download';
  document.getElementById('delivery').listeners.change();
  globalThis.fetch = async path => {
    assert.equal(path, '/api/convert');
    return new Response('<html>Sign in</html>', {headers: {'Content-Type': 'text/html'}});
  };
  await document.getElementById('article-form').listeners.submit({preventDefault() {}});
  assert.equal(document.getElementById('download').hidden, true);
  assert.match(document.getElementById('status').textContent, /sign.in/i);
});
