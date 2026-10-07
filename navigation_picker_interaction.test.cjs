const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync('app.js', 'utf8');
const script = source.slice(source.indexOf('function initDirectionsPicker(){'));
assert.ok(script, 'navigation picker implementation must exist');

function element(dataset = {}) {
  const listeners = new Map();
  return {
    dataset, hidden: false, open: false, listeners, focused: false,
    addEventListener(name, callback) { listeners.set(name, callback); },
    emit(name, event = {}) { return listeners.get(name)?.(event); },
    focus() { this.focused = true; },
    showModal() { this.open = true; },
    close() { this.open = false; this.emit('close'); },
  };
}
function load(userAgent, options = {}) {
  const open = element();
  const dialog = element();
  const close = element();
  const elements = Object.fromEntries(['android', 'apple', 'share'].map(name => [name, element({ navigationApp: name })]));
  const links = ['waze', 'google', 'apple', 'android'].map(name => element({ navigationApp: name }));
  dialog.querySelector = selector => {
    if (selector === '.directions-dialog-close') return close;
    return elements[selector.match(/data-navigation-app="(.*)"/)?.[1]];
  };
  dialog.querySelectorAll = () => links;
  dialog.getBoundingClientRect = () => ({ left: 20, top: 20, right: 400, bottom: 480 });
  if (options.noDialog) delete dialog.showModal;
  const events = [];
  const navigator = { userAgent, platform: '', maxTouchPoints: 0 };
  if (options.share) navigator.share = async () => undefined;
  vm.runInNewContext(script, {
    document: { querySelector: selector => selector === '#directionsOpen' ? open : dialog },
    navigator, trackEvent: (name, data) => events.push([name, data]), console,
  });
  return { open, dialog, close, elements, links, events };
}
test('iOS dialog opens on tap, supports Waze and restores keyboard focus on close', () => {
  const app = load('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)', { share: true });
  assert.equal(app.elements.android.hidden, true);
  assert.equal(app.elements.apple.hidden, false);
  assert.equal(app.elements.share.hidden, false);
  let prevented = false;
  app.open.emit('click', { preventDefault() { prevented = true; } });
  assert.equal(prevented, true);
  assert.equal(app.dialog.open, true);
  assert.equal(app.events[0][0], 'directions_picker_open');
  app.links[0].emit('click');
  assert.equal(app.events.at(-1)[1].application, 'waze');
  assert.equal(app.dialog.open, false);
  assert.equal(app.open.focused, true);
});
test('Android offers system maps link and hides Apple Plans and sharing fallback', () => {
  const app = load('Mozilla/5.0 (Linux; Android 15; Pixel 8)');
  assert.equal(app.elements.android.hidden, false);
  assert.equal(app.elements.apple.hidden, true);
  assert.equal(app.elements.share.hidden, true);
  app.open.emit('click', { preventDefault() {} });
  app.links[3].emit('click');
  assert.equal(app.events.at(-1)[1].application, 'android');
});
test('without dialog API the standard Google Maps link remains active', () => {
  const app = load('Mozilla/5.0 (iPhone)', { noDialog: true });
  assert.equal(app.open.listeners.has('click'), false);
});
test('closing with close button or backdrop restores focus', () => {
  const app = load('Mozilla/5.0');
  app.open.emit('click', { preventDefault() {} });
  app.close.emit('click');
  assert.equal(app.dialog.open, false);
  app.open.focused = false;
  app.open.emit('click', { preventDefault() {} });
  app.dialog.emit('click', { target: app.dialog, clientX: 0, clientY: 0 });
  assert.equal(app.dialog.open, false);
  assert.equal(app.open.focused, true);
});
test('native share sheet is used only on direct user selection', async () => {
  const app = load('Mozilla/5.0 (iPhone)', { share: true });
  app.open.emit('click', { preventDefault() {} });
  await app.elements.share.emit('click');
  assert.equal(app.dialog.open, false);
  assert.equal(app.events.at(-1)[1].application, 'share');
});
