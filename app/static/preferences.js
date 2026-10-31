const KEY = 'remarkable.preferences.v1';
const defaults = {format: 'pdf', folder: '', delivery: 'send'};

function normalize(value = {}) {
  return {
    format: ['pdf', 'epub'].includes(value?.format) ? value.format : defaults.format,
    folder: typeof value?.folder === 'string' && value.folder.length <= 128 ? value.folder : '',
    delivery: ['send', 'download'].includes(value?.delivery) ? value.delivery : defaults.delivery,
  };
}

export function loadPreferences(storage) {
  try { return normalize(JSON.parse(storage.getItem(KEY))); }
  catch { return {...defaults}; }
}

export function savePreferences(storage, value) {
  try { storage.setItem(KEY, JSON.stringify(normalize(value))); } catch { /* Private browsing. */ }
}

export function reconcileFolder(value, folders, storage) {
  const updated = {...value, folder: folders.some(f => f.id === value.folder) ? value.folder : ''};
  savePreferences(storage, updated);
  return updated;
}

export function sharedURL(search) {
  const params = new URLSearchParams(search);
  for (const key of ['url', 'text', 'title']) {
    const value = params.get(key) || '';
    const match = value.match(/https?:\/\/[^\s<>"\u0000-\u001f]+/i);
    if (match) {
      try {
        const url = new URL(match[0]);
        if (['https:', 'http:'].includes(url.protocol)) return url.href;
      } catch { /* Try the next field. */ }
    }
  }
  return '';
}

export function bookmarklet(baseURL) {
  const target = JSON.stringify(baseURL.replace(/\/$/, '') + '/?url=');
  return `javascript:(()=>{window.open(${target}+encodeURIComponent(location.href),'_blank','noopener')})()`;
}
