import test from 'node:test';
import assert from 'node:assert/strict';
import {loadPreferences, savePreferences, reconcileFolder, sharedURL, bookmarklet} from '../app/static/preferences.js';

function memory() {
  const data = new Map();
  return {getItem: k => data.get(k) ?? null, setItem: (k, v) => data.set(k, v)};
}

test('preferences persist on one device without leaking to another', () => {
  const a = memory(), b = memory();
  savePreferences(a, {format: 'epub', folder: 'science', delivery: 'download', url: 'secret'});
  assert.deepEqual(loadPreferences(a), {format: 'epub', folder: 'science', delivery: 'download'});
  assert.deepEqual(loadPreferences(b), {format: 'pdf', folder: '', delivery: 'send'});
  assert.ok(!a.getItem('remarkable.preferences.v1').includes('secret'));
});

test('invalid storage and disabled storage fall back safely', () => {
  const storage = memory();
  storage.setItem('remarkable.preferences.v1', '{');
  assert.equal(loadPreferences(storage).format, 'pdf');
  storage.setItem('remarkable.preferences.v1', JSON.stringify({format: 'exe', delivery: 'email'}));
  assert.equal(loadPreferences(storage).delivery, 'send');
  assert.doesNotThrow(() => savePreferences({setItem() { throw Error(); }}, {}));
});

test('deleted folder resets stored preference to root', () => {
  const storage = memory();
  const preferences = {format: 'epub', folder: 'gone', delivery: 'send'};
  const updated = reconcileFolder(preferences, [{id: ''}, {id: 'science'}], storage);
  assert.equal(updated.folder, '');
  assert.equal(loadPreferences(storage).folder, '');
  assert.equal(reconcileFolder({...preferences, folder: 'science'}, [{id: 'science'}], storage).folder, 'science');
});

test('share fields prefer url then text then title', () => {
  assert.equal(sharedURL('?url=https%3A%2F%2Fexample.org%2Fa&text=https://other.org'), 'https://example.org/a');
  assert.equal(sharedURL('?text=An+article+https://example.org/story'), 'https://example.org/story');
  assert.equal(sharedURL('?title=https://example.org'), 'https://example.org/');
  assert.equal(sharedURL('?url=javascript:alert(1)&text=No+URL'), '');
});

test('bookmarklet captures current URL and configurable base', () => {
  const code = bookmarklet('https://reader.example');
  assert.ok(code.startsWith('javascript:'));
  let opened;
  const window = {open: (...args) => { opened = args; }};
  Function('window', 'location', code.slice(11))(window, {href: 'https://article.example/a?b=2&c=3'});
  assert.equal(opened[0], 'https://reader.example/?url=https%3A%2F%2Farticle.example%2Fa%3Fb%3D2%26c%3D3');
  assert.equal(opened[2], 'noopener');
});
