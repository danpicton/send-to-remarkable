import test from 'node:test';
import assert from 'node:assert/strict';

const fetchBlob = globalThis.fetch;

class Element {
  value = ''; hidden = false; disabled = false; textContent = ''; dataset = {};
  listeners = {}; selectedOptions = [{textContent: '/Reading'}];
  addEventListener(name, callback) { this.listeners[name] = callback; }
  replaceChildren(...children) { this.children = children; }
  click() { this.clicked = true; }
  focus() { this.focused = true; }
  removeAttribute(name) { delete this[name]; }
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
    if (path === '/api/extract') return Response.json({title: 'Shared story'});
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
  assert.equal(element('title').value, 'Shared story');
  await element('article-form').listeners.submit({preventDefault() {}});
  assert.equal(element('download').hidden, false);
  assert.equal(element('confirmation').hidden, true);
  assert.equal(element('preview').hidden, false);
  assert.equal(element('preview').href, element('download').href);
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

test('session login preserves shared URL, handles expiry, and signs out', async () => {
  const nodes = new Map();
  const element = id => {
    if (!nodes.has(id)) nodes.set(id, new Element());
    return nodes.get(id);
  };
  globalThis.document = {getElementById: element, createElement: () => new Element()};
  globalThis.location = {search: '?url=https://example.org/shared'};
  let authenticated = false;
  globalThis.fetch = async (path, options) => {
    if (path === '/api/auth/session') return Response.json({enabled: true, authenticated});
    if (path === '/api/auth/login') {
      assert.deepEqual(JSON.parse(options.body), {username: 'reader', password: 'password'});
      authenticated = true;
      return Response.json({ok: true});
    }
    if (path === '/api/auth/logout') {
      authenticated = false;
      return Response.json({ok: true});
    }
    if (!authenticated) return Response.json({error: {message: 'Sign in to continue.'}}, {status: 401});
    if (path === '/api/extract') return Response.json({title: 'Shared article after login'});
    if (path === '/api/config') return Response.json({base_url: 'https://reader.example'});
    if (path === '/api/folders') return Response.json({folders: [{id: '', path: '/'}]});
    throw Error(`Unexpected request: ${path}`);
  };
  await import('../app/static/app.js?session-test');
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(element('login-form').hidden, false);
  assert.equal(element('article-form').hidden, true);
  assert.equal(element('url').value, 'https://example.org/shared');
  assert.equal(element('title').value, '');
  element('username').value = 'reader';
  element('password').value = 'password';
  await element('login-form').listeners.submit({preventDefault() {}});
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(element('password').value, '');
  assert.equal(element('login-form').hidden, true);
  assert.equal(element('article-form').hidden, false);
  assert.equal(element('url').value, 'https://example.org/shared');
  assert.equal(element('title').value, 'Shared article after login');
  authenticated = false;
  await element('refresh').listeners.click();
  assert.equal(element('login-form').hidden, false);
  assert.equal(element('url').value, 'https://example.org/shared');
  authenticated = true;
  await element('logout').listeners.click();
  assert.equal(authenticated, false);
  assert.equal(element('url').value, '');
  assert.equal(element('download').hidden, true);
});

test('page titles can be edited, Unicode filenames survive, and URL changes reset titles', async () => {
  const element = id => document.getElementById(id);
  const filename = 'Café: a reader’s guide (3.2)?.pdf';
  let payload;
  globalThis.fetch = async (path, options) => {
    if (path === '/api/extract') return Response.json({title: 'Original page title'});
    if (path === '/api/convert') {
      payload = JSON.parse(options.body);
      return new Response('%PDF-test', {headers: {
        'Content-Type': 'application/pdf',
        'Content-Disposition': `attachment; filename="article.pdf"; filename*=UTF-8''${encodeURIComponent(filename)}`,
      }});
    }
    if (path === '/api/send') {
      assert.equal(options.body.get('file').name, filename);
      return Response.json({id: 'uploaded'});
    }
    throw Error(`Unexpected request: ${path}`);
  };
  element('url').value = 'https://example.org/story';
  await element('page-title').listeners.click();
  assert.equal(element('title').value, 'Original page title');
  element('title').value = 'Café: a reader’s guide (3.2)?';
  await element('article-form').listeners.submit({preventDefault() {}});
  assert.equal(payload.title, element('title').value);
  assert.equal(element('download').download, filename);
  assert.equal(element('title').disabled, false);
  element('url').value = 'https://example.org/next';
  element('url').listeners.input();
  assert.equal(element('title').value, '');
  await element('article-form').listeners.submit({preventDefault() {}});
  assert.equal(payload.title, null);
  URL.revokeObjectURL(element('download').href);
});

test('failure to load the page title preserves the editable title and restores controls', async () => {
  const element = id => document.getElementById(id);
  element('title').value = 'My title';
  globalThis.fetch = async () => Response.json({error: {message: 'Could not read page'}}, {status: 422});
  await element('page-title').listeners.click();
  assert.equal(element('title').value, 'My title');
  assert.equal(element('page-title').disabled, false);
  assert.match(element('status').textContent, /Could not read page/);
});

test('automatic title loading debounces URL edits, preserves edits, and restores the original', async () => {
  const nodes = new Map();
  const element = id => {
    if (!nodes.has(id)) nodes.set(id, new Element());
    return nodes.get(id);
  };
  globalThis.document = {getElementById: element, createElement: () => new Element()};
  globalThis.location = {search: ''};
  const pending = [];
  globalThis.fetch = async (path, options) => {
    if (path === '/api/auth/session') return Response.json({enabled: false});
    if (path === '/api/config') return Response.json({base_url: 'https://reader.example'});
    if (path === '/api/folders') return Response.json({folders: []});
    if (path === '/api/extract') {
      return new Promise(resolve => pending.push({url: JSON.parse(options.body).url, resolve}));
    }
    throw Error(`Unexpected request: ${path}`);
  };
  await import('../app/static/app.js?automatic-title-test');
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(pending.length, 0);

  for (const url of ['https://example.org/first', 'https://example.org/second']) {
    element('url').value = url;
    element('url').listeners.input();
  }
  await new Promise(resolve => setTimeout(resolve, 450));
  assert.equal(pending.length, 1);
  assert.equal(pending[0].url, 'https://example.org/second');
  assert.equal(element('title').disabled, false);
  element('title').value = 'My edited title';
  element('title').listeners.input();
  pending[0].resolve(Response.json({title: 'Original title'}));
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(element('title').value, 'My edited title');
  await element('page-title').listeners.click();
  assert.equal(element('title').value, 'Original title');
  assert.equal(pending.length, 1, 'restoring uses the already loaded title');

  element('url').value = 'https://example.org/third';
  element('url').listeners.input();
  assert.equal(element('title').value, '');
  await new Promise(resolve => setTimeout(resolve, 450));
  element('url').value = 'https://example.org/fourth';
  element('url').listeners.input();
  pending[1].resolve(Response.json({title: 'Stale title'}));
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(element('title').value, '');
  await new Promise(resolve => setTimeout(resolve, 450));
  pending[2].resolve(Response.json({title: 'Fourth title'}));
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(element('title').value, 'Fourth title');

  element('url').value = 'https://example.org/failing';
  element('url').listeners.input();
  await new Promise(resolve => setTimeout(resolve, 450));
  pending[3].resolve(Response.json({error: {message: 'Could not read page'}}, {status: 422}));
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(element('title').value, '');
  assert.equal(element('submit').disabled, false);
  assert.match(element('title-hint').textContent, /Could not read page/);
});

test('Medium shares check Freedium availability and ignore stale checks after URL edits', async () => {
  const nodes = new Map();
  const element = id => {
    if (!nodes.has(id)) nodes.set(id, new Element());
    return nodes.get(id);
  };
  globalThis.document = {getElementById: element, createElement: () => new Element()};
  globalThis.location = {search: '?url=https://medium.com/@reader/story'};
  const checks = [];
  globalThis.fetch = async (path, options) => {
    if (path === '/api/auth/session') return Response.json({enabled: false});
    if (path === '/api/config') return Response.json({base_url: 'https://reader.example'});
    if (path === '/api/folders') return Response.json({folders: []});
    if (path === '/api/extract') return Response.json({title: 'Medium story'});
    if (path === '/api/freedium/status') {
      assert.equal(options.credentials, 'same-origin');
      assert.equal(options.cache, 'no-store');
      return new Promise(resolve => checks.push(resolve));
    }
    throw Error(`Unexpected request: ${path}`);
  };
  await import('../app/static/app.js?freedium-test');
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(element('freedium-status').hidden, false);
  assert.match(element('freedium-status').textContent, /Checking freedium/);
  checks[0](Response.json({available: true}));
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.match(element('freedium-status').textContent, /is up/);
  assert.equal(element('freedium-status').dataset.kind, 'success');

  element('url').value = 'https://reader.medium.com/next';
  element('url').listeners.input();
  await new Promise(resolve => setTimeout(resolve, 450));
  checks[1](Response.json({available: false}));
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.match(element('freedium-status').textContent, /unavailable/);
  assert.equal(element('freedium-status').dataset.kind, 'error');

  await element('page-title').listeners.click();
  element('url').value = 'https://medium.com.evil.example/story';
  element('url').listeners.input();
  assert.equal(element('freedium-status').hidden, true);
  checks[2](Response.json({available: true}));
  await new Promise(resolve => setTimeout(resolve, 450));
  assert.equal(element('freedium-status').hidden, true);
  assert.equal(element('freedium-status').textContent, '');
  assert.equal(checks.length, 3, 'other sites do not trigger a Freedium check');

  element('url').value = 'https://medium.com/another';
  element('url').listeners.input();
  await new Promise(resolve => setTimeout(resolve, 450));
  checks[3](Response.json({error: {message: 'Offline'}}, {status: 502}));
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.match(element('freedium-status').textContent, /Could not check/);
  assert.equal(element('submit').disabled, false);
});

test('confirmation waits for delivery, previews the original PDF, and returns to a fresh form', async () => {
  const nodes = new Map();
  const element = id => {
    if (!nodes.has(id)) nodes.set(id, new Element());
    return nodes.get(id);
  };
  globalThis.document = {getElementById: element, createElement: () => new Element()};
  globalThis.location = {search: ''};
  let finishSend;
  let format = 'pdf';
  let uploads = 0;
  globalThis.fetch = async path => {
    if (path === '/api/auth/session') return Response.json({enabled: false});
    if (path === '/api/config') return Response.json({base_url: 'https://reader.example'});
    if (path === '/api/folders') return Response.json({folders: [{id: '', path: '/'}]});
    if (path === '/api/convert') return new Response(format === 'pdf' ? '%PDF-original' : 'epub', {headers: {
      'Content-Type': format === 'pdf' ? 'application/pdf' : 'application/epub+zip',
      'Content-Disposition': `attachment; filename="Garden.${format}"`,
    }});
    if (path === '/api/send') {
      uploads++;
      return new Promise(resolve => { finishSend = resolve; });
    }
    throw Error(`Unexpected request: ${path}`);
  };
  await import('../app/static/app.js?confirmation-test');
  await new Promise(resolve => setTimeout(resolve, 0));
  element('url').value = 'https://example.org/story';
  element('title').value = 'Garden';
  const submitted = element('article-form').listeners.submit({preventDefault() {}});
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(element('confirmation').hidden, true, 'upload is still pending');
  assert.equal(element('article-form').hidden, false);
  finishSend(Response.json({id: 'uploaded'}));
  await submitted;
  assert.equal(element('confirmation').hidden, false);
  assert.equal(element('article-form').hidden, true);
  assert.equal(element('page-header').hidden, true);
  assert.equal(element('sharing').hidden, true);
  assert.equal(element('confirmation-title').textContent, 'Article sent');
  assert.equal(element('confirmation-title').focused, true);
  assert.match(element('confirmation-message').textContent, /after synchronisation/);
  assert.equal(element('document-title').textContent, 'Garden');
  assert.equal(element('document-destination').textContent, 'Sent to /Reading');
  assert.equal(element('preview').hidden, false);
  assert.equal(element('preview').href, element('download').href);
  const pdfURL = element('preview').href;
  assert.equal(await (await fetchBlob(pdfURL)).text(), '%PDF-original');
  element('send-another').listeners.click();
  assert.equal(element('confirmation').hidden, true);
  assert.equal(element('article-form').hidden, false);
  assert.equal(element('page-header').hidden, false);
  assert.equal(element('sharing').hidden, false);
  assert.equal(element('url').value, '');
  assert.equal(element('title').value, '');
  assert.equal(element('url').focused, true);
  assert.equal(element('preview').href, undefined);
  assert.equal(element('download').hidden, true);
  await assert.rejects(fetchBlob(pdfURL), 'starting another article releases the old document');

  // Download-only EPUBs get accurate copy, keep the download, and offer no PDF preview.
  format = 'epub';
  element('format').value = format;
  element('format').listeners.change();
  element('delivery').value = 'download';
  element('delivery').listeners.change();
  element('url').value = 'https://example.org/next';
  await element('article-form').listeners.submit({preventDefault() {}});
  assert.equal(uploads, 1);
  assert.equal(element('confirmation-title').textContent, 'Your article is ready');
  assert.equal(element('document-format').textContent, 'EPUB');
  assert.equal(element('download').download, 'Garden.epub');
  assert.equal(element('download').clicked, true);
  assert.equal(element('preview').hidden, true);
  assert.equal(element('preview-hint').hidden, true);
  element('send-another').listeners.click();
});
