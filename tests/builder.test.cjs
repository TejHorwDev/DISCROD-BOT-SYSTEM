// DOM-level regression tests for the real dashboard script; Discord is mocked.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { JSDOM, VirtualConsole } = require('jsdom');

const root = path.join(__dirname, '..');
const html = fs.readFileSync(path.join(root, 'templates/index.html'), 'utf8');
const script = fs.readFileSync(path.join(root, 'static/app.js'), 'utf8');
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));

async function dashboard() {
  const errors = [];
  const requests = [];
  const virtualConsole = new VirtualConsole();
  virtualConsole.on('jsdomError', error => errors.push(error));
  const dom = new JSDOM(html, { url: 'http://localhost:5000/', runScripts: 'outside-only', virtualConsole });
  const w = dom.window;
  w.addEventListener('error', event => errors.push(event.error || event.message));
  w.fetch = async (url, options = {}) => {
    const payload = options.body && typeof options.body === 'string' ? JSON.parse(options.body) : null;
    requests.push({ url, payload });
    let data = { ok: true, settings: {}, styles: [], themes: [], bots: [], guilds: [], products: [], history: [], schedules: [], sections: [], links: [], uploads: [] };
    if (url === '/api/preview') data = { ok: true, messages: [{content: '', embeds: [], files: []}], usage: {}, errors: [], warnings: [], report: { splits: [] } };
    if (url.startsWith('/api/status')) data = { ok: false, connected: false, error: 'No bot in test' };
    return { status: 200, json: async () => data };
  };
  w.eval(script);
  await wait(80);
  return { dom, w, document: w.document, errors, requests };
}

function input(w, node, value) {
  node.value = value;
  node.dispatchEvent(new w.Event('input', { bubbles: true }));
}

test('builder starts and pricing rows can be edited, added, reordered and removed', async () => {
  const { dom, w, document: d, errors, requests } = await dashboard();
  try {
    assert.deepEqual(errors, []);
    assert.equal(d.querySelectorAll('#plansEditor .plan-row').length, 1);
    assert.ok(d.querySelector('#builderButtonsList').textContent.includes('No buttons'));
    input(w, d.querySelector('#f-name'), 'External Panel');
    input(w, d.querySelector('.plan-price'), '4.99');
    d.querySelector('.plan-quick').click();
    assert.equal(d.querySelectorAll('#plansEditor .plan-row').length, 2);
    input(w, d.querySelectorAll('.plan-price')[1], '9.99');
    d.querySelectorAll('.plan-row')[1].querySelector('[aria-label^="Move up"]').click();
    assert.equal(d.querySelectorAll('.plan-price')[0].value, '9.99');
    assert.equal(d.querySelectorAll('.plan-price')[1].value, '4.99');
    d.querySelectorAll('.plan-remove')[1].click();
    assert.equal(d.querySelectorAll('#plansEditor .plan-row').length, 1);
    await wait(400);
    const preview = requests.filter(r => r.url === '/api/preview' && r.payload.content.kind === 'product').at(-1);
    assert.equal(preview.payload.content.name, 'External Panel');
    assert.equal(preview.payload.content.plans[0].price, '9.99');
    assert.deepEqual(errors, []);
  } finally { dom.window.close(); }
});

test('custom fields and link buttons initialize and update the preview model', async () => {
  const { dom, w, document: d, errors, requests } = await dashboard();
  try {
    d.querySelector('#addCustomField').click();
    input(w, d.querySelector('#customFieldsEditor input[type=text]'), 'Compatibility');
    input(w, d.querySelector('#customFieldsEditor textarea'), 'Windows 11');
    d.querySelector('#btnAddCustomBtn').click();
    const url = d.querySelector('#builderButtonsList input[type=url]');
    input(w, url, 'https://example.com');
    await wait(400);
    const preview = requests.filter(r => r.url === '/api/preview' && r.payload.content.kind === 'product').at(-1);
    assert.equal(preview.payload.content.customFields[0].value, 'Windows 11');
    assert.equal(preview.payload.content.buttons[0].url, 'https://example.com');
    assert.deepEqual(errors, []);
  } finally { dom.window.close(); }
});

test('sending waits while an edited preview is still pending', async () => {
  const { dom, w, document: d, errors, requests } = await dashboard();
  try {
    input(w, d.querySelector('#f-name'), 'New product');
    assert.equal(d.querySelector('#btn-send').disabled, true);
    assert.equal(d.querySelector('#btn-send-test').disabled, true);
    d.dispatchEvent(new w.KeyboardEvent('keydown', { key: 'Enter', ctrlKey: true, bubbles: true }));
    await wait(30);
    assert.equal(requests.some(r => r.url === '/api/send'), false);
    await wait(400);
    assert.deepEqual(errors, []);
  } finally { dom.window.close(); }
});

test('a delayed old preview cannot replace newer edits during debounce', async () => {
  const { dom, w, document: d, errors } = await dashboard();
  try {
    await wait(400);
    const originalFetch = w.fetch;
    let finishOld;
    w.fetch = (url, options) => url === '/api/preview'
      ? new Promise(resolve => { finishOld = resolve; })
      : originalFetch(url, options);
    input(w, d.querySelector('#f-name'), 'First version');
    await wait(330);
    assert.equal(typeof finishOld, 'function');
    input(w, d.querySelector('#f-name'), 'Changed while loading');
    finishOld({ status: 200, json: async () => ({ok: false, messages: [], usage: {}, errors: ['obsolete preview'], warnings: [], report: {splits: []}}) });
    await wait(20);
    assert.equal(d.querySelector('#pfWarnings').textContent.includes('obsolete preview'), false);
    assert.equal(d.querySelector('#btn-send').disabled, true);
    w.fetch = originalFetch;
    await wait(400);
    assert.equal(d.querySelector('#pfWarnings').textContent.includes('obsolete preview'), false);
    assert.deepEqual(errors, []);
  } finally { dom.window.close(); }
});
