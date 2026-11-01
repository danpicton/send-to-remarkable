import {loadPreferences, savePreferences, reconcileFolder, sharedURL, bookmarklet} from './preferences.js';

const $ = id => document.getElementById(id);
let storage;
try { storage = localStorage; } catch { storage = null; }
let prefs = loadPreferences(storage);
let fileURL = null;
let busy = false;
let loadingFolders = false;
let hasFolders = false;
let bookmarkCode = '';
let sessionLogin = false;

function showLogin() {
  $('login-form').hidden = false;
  $('article-form').hidden = true;
  $('logout').hidden = true;
}


$('format').value = prefs.format;
$('delivery').value = prefs.delivery;
$('url').value = sharedURL(location.search);
// Avoid retaining the shared article in the address bar/history for subsequent navigation.
if (location.search) history.replaceState(null, '', '/');

function status(message, kind = '') {
  $('status').textContent = message;
  $('status').dataset.kind = kind;
}
function controls() {
  for (const id of ['url', 'title', 'page-title', 'format', 'delivery', 'submit']) $(id).disabled = busy;
  $('folder-section').hidden = prefs.delivery === 'download';
  $('folder').disabled = busy || loadingFolders || !hasFolders;
  $('refresh').disabled = busy || loadingFolders;
  $('submit').textContent = busy ? 'Working…' : prefs.delivery === 'send' ? 'Send to reMarkable' : 'Create download';
}
for (const id of ['format', 'delivery', 'folder']) {
  $(id).addEventListener('change', () => {
    prefs[id] = $(id).value;
    savePreferences(storage, prefs);
    controls();
  });
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options, credentials: 'same-origin', cache: 'no-store', redirect: 'error',
    headers: {...options.headers, 'X-Requested-With': 'SendToRemarkable'},
    signal: AbortSignal.timeout(180000),
  });
  if (!response.ok) {
    if (response.status === 401 && sessionLogin) showLogin();
    let message = `Request failed (HTTP ${response.status}).`;
    try { message = (await response.json()).error.message || message; } catch { /* Proxy errors. */ }
    const error = new Error(message);
    error.status = response.status;
    throw error;
  }
  return response;
}

async function loadFolders() {
  if (loadingFolders) return;
  loadingFolders = true;
  controls();
  $('folder-status').textContent = 'Loading folders…';
  try {
    const {folders} = await (await api('/api/folders')).json();
    const previous = prefs.folder;
    prefs = reconcileFolder(prefs, folders, storage);
    $('folder').replaceChildren(...folders.map(folder => {
      const option = document.createElement('option');
      option.value = folder.id;
      option.textContent = folder.id ? folder.path : 'Root';
      return option;
    }));
    $('folder').value = prefs.folder;
    hasFolders = true;
    $('folder-status').textContent = previous !== prefs.folder ? 'Previous folder was removed. Root selected.' : '';
  } catch (error) {
    $('folder-status').textContent = `${error.message} Local download is available.`;
    // A failed request is not proof that a saved folder was deleted.
  } finally {
    loadingFolders = false;
    controls();
  }
}
$('refresh').addEventListener('click', loadFolders);
$('url').addEventListener('input', () => { $('title').value = ''; });
$('page-title').addEventListener('click', async () => {
  if (busy) return;
  busy = true;
  controls();
  status('Reading the page title…');
  try {
    const article = await (await api('/api/extract', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({url: $('url').value.trim()}),
    })).json();
    $('title').value = article.title;
    status('Page title loaded. You can edit it before sending.');
  } catch (error) {
    status(error.message, 'error');
  } finally {
    busy = false;
    controls();
  }
});

$('article-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (busy) return;
  busy = true;
  controls();
  if (fileURL) URL.revokeObjectURL(fileURL);
  fileURL = null;
  $('download').hidden = true;
  let converted = false;
  try {
    status('Extracting the article and preparing your document…');
    const response = await api('/api/convert', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({url: $('url').value.trim(), format: prefs.format, title: $('title').value.trim() || null}),
    });
    const expectedType = prefs.format === 'pdf' ? 'application/pdf' : 'application/epub+zip';
    if (response.headers.get('Content-Type')?.split(';')[0] !== expectedType) {
      throw new Error('Unexpected response. Check your proxy sign-in and try again.');
    }
    const blob = await response.blob();
    const disposition = response.headers.get('Content-Disposition') || '';
    const encodedName = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
    const filename = encodedName ? decodeURIComponent(encodedName)
      : disposition.match(/filename="([^"]+)"/)?.[1] || `article.${prefs.format}`;
    fileURL = URL.createObjectURL(blob);
    $('download').href = fileURL;
    $('download').download = filename;
    $('download').textContent = `Download ${prefs.format.toUpperCase()}`;
    $('download').hidden = false;
    converted = true;
    if (prefs.delivery === 'download') {
      status('Your document is ready.', 'success');
      $('download').click();
    } else {
      status('Document ready. Sending to reMarkable…');
      const form = new FormData();
      form.append('folder', prefs.folder);
      form.append('file', blob, filename);
      await api('/api/send', {method: 'POST', body: form});
      const folderName = $('folder').selectedOptions[0]?.textContent || 'the selected folder';
      status(`Sent to ${folderName}. It will appear on your reMarkable after synchronisation.`, 'success');
    }
  } catch (error) {
    const detail = error.name === 'TimeoutError' ? 'The request timed out. Check your tablet before retrying an upload.'
      : error instanceof TypeError ? 'Could not reach the app. Check your connection and proxy sign-in.' : error.message;
    status(converted ? `${detail} Your converted document is ready to download below.` : detail, 'error');
  } finally {
    busy = false;
    controls();
  }
});

async function setupBookmarklet() {
  try {
    const {base_url} = await (await api('/api/config')).json();
    bookmarkCode = bookmarklet(base_url);
    $('bookmarklet').href = bookmarkCode;
  } catch {
    $('bookmark-status').textContent = 'Connect and sign in to set up the bookmarklet.';
  }
}
$('bookmarklet').addEventListener('click', event => event.preventDefault());
$('copy-bookmarklet').addEventListener('click', async () => {
  try {
    if (!bookmarkCode) throw new Error();
    await navigator.clipboard.writeText(bookmarkCode);
    $('bookmark-status').textContent = 'Copied. Paste it into a bookmark’s URL field.';
  } catch {
    $('bookmark-status').textContent = 'Copy unavailable. Drag the bookmarklet link to your bookmarks bar instead.';
  }
});
$('login-form').addEventListener('submit', async event => {
  event.preventDefault();
  $('login-submit').disabled = true;
  $('login-status').textContent = '';
  try {
    await api('/api/auth/login', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({username: $('username').value, password: $('password').value}),
    });
    $('password').value = '';
    $('login-form').hidden = true;
    $('article-form').hidden = false;
    $('logout').hidden = false;
    loadFolders();
    setupBookmarklet();
  } catch (error) {
    $('login-status').textContent = error.message;
  } finally {
    $('login-submit').disabled = false;
  }
});
$('logout').addEventListener('click', async () => {
  try {
    await api('/api/auth/logout', {method: 'POST'});
    if (fileURL) URL.revokeObjectURL(fileURL);
    fileURL = null;
    $('download').hidden = true;
    $('url').value = '';
    $('title').value = '';
    status('');
    showLogin();
  } catch (error) {
    status(error.message, 'error');
  }
});
async function start() {
  controls();
  try {
    const session = await (await api('/api/auth/session')).json();
    sessionLogin = session.enabled;
    if (sessionLogin && !session.authenticated) {
      showLogin();
      return;
    }
    $('logout').hidden = !sessionLogin;
  } catch { /* Offline/proxy mode: existing API errors explain unavailable access. */ }
  loadFolders();
  setupBookmarklet();
}
start();
if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(() => {});
window.addEventListener('online', loadFolders);
