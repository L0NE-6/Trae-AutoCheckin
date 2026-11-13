'use strict';

const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const htmlPath = process.argv[2];
if (!htmlPath) throw new Error('usage: node config_builder_harness.js <html>');
const html = fs.readFileSync(htmlPath, 'utf8');
const scripts = [...html.matchAll(/<script>\s*([\s\S]*?)\s*<\/script>/g)];
assert.strictEqual(scripts.length, 1, 'expected one inline script');

class MockElement {
  constructor(id) {
    this.id = id;
    this.value = '';
    this.checked = false;
    this.textContent = '';
    this.innerHTML = '';
    this.files = [];
    this.style = {};
    this.classList = { add() {}, remove() {} };
    this.parentNode = { querySelector() { return null; } };
  }
  appendChild(child) { this.child = child; return child; }
  select() {}
  click() { context.clickCount += 1; }
}

const ids = [
  'accounts', 'accCount', 'output', 'byteCount', 'autoBox', 'autoTip',
  'importBox', 'impTip', 'filePick', 'devKey', 'devPub', 'devMid', 'devDid',
  'devName', 'devModel', 'devBrand', 'qywx', 'pp', 'schOnly', 'schBatch',
  'schPeak', 'schCool', 'schPCool', 'schTries', 'schJit', 'schRotate',
  'schVerify', 'schCircuit', 'advClient', 'advCache', 'advAccDir',
  'advStorage', 'tip', 'dupWarn'
];
const elements = Object.fromEntries(ids.map(id => [id, new MockElement(id)]));
elements.schPeak.value = '0';
elements.schCool.value = '55';
elements.schPCool.value = '12';
elements.schTries.value = '1';
elements.schJit.checked = true;
elements.schRotate.checked = true;
elements.schVerify.checked = true;

let confirmAnswer = true;
let lastBlobText = '';
const context = {
  console,
  JSON,
  Math,
  String,
  Object,
  Array,
  Boolean,
  Set,
  Number,
  Blob: class MockBlob {
    constructor(parts) {
      lastBlobText = String(parts.join(''));
    }
  },
  URL: {
    createObjectURL() { return 'blob:mock'; },
    revokeObjectURL() {}
  },
  document: {
    getElementById(id) {
      if (!elements[id]) throw new Error('missing element: ' + id);
      return elements[id];
    },
    createElement(tag) { return new MockElement(tag); },
    addEventListener() {}
  },
  window: { addEventListener() {} },
  navigator: {
    clipboard: { writeText: async function () {} },
    sendBeacon() { return true; }
  },
  alert() {},
  confirm() {
    context.confirmCount += 1;
    return confirmAnswer;
  },
  setTimeout(fn) {
    if (fn) fn();
    return 1;
  },
  clearTimeout() {},
  setInterval() { return 1; },
  clearInterval() {},
  clickCount: 0,
  confirmCount: 0
};
context.globalThis = context;
vm.createContext(context);
vm.runInContext(scripts[0][1], context, { filename: 'trae_config_builder.inline.js' });

const run = expression => vm.runInContext(expression, context);
const canonical = value => JSON.stringify(value, Object.keys(value).sort());

run('state.accounts = [blankAccount()]; render()');
assert.strictEqual(elements.output.value, '{}', 'empty form exported a fake credential');

const inputConfig = {
  accounts: [{
    accessToken: 'AT_ONLY',
    deviceId: 'ACCOUNT_DEVICE',
    realDeviceId: 'ACCOUNT_REAL_DEVICE',
    deviceKeyPem: 'ACCOUNT_KEY\\nLINE',
    devicePubPem: 'ACCOUNT_PUB\\nLINE',
    machineId: 'ACCOUNT_MACHINE',
    icubeAuth: 'ICUBE_VALUE',
    storagePath: 'C:\\Trae\\storage.json',
    uid: 'UID_AT'
  }, {
    refreshToken: 'REFRESH_ONLY'
  }],
  device: {
    keyPem: 'GLOBAL_KEY',
    pubPem: 'GLOBAL_PUB',
    machineId: 'GLOBAL_MACHINE',
    deviceId: 'GLOBAL_DEVICE',
    name: 'GLOBAL_NAME',
    model: 'GLOBAL_MODEL',
    brand: 'GLOBAL_BRAND'
  }
};
context.inputConfig = inputConfig;
run('applyConfigToForm(inputConfig)');
const exported = run('buildConfig()');

assert.strictEqual(exported.accounts.length, 2, 'accessToken-only account was dropped');
assert.strictEqual(canonical(exported.accounts[0]), canonical(inputConfig.accounts[0]));
assert.strictEqual(canonical(exported.accounts[1]), canonical(inputConfig.accounts[1]));
assert.strictEqual(exported.device.name, 'GLOBAL_NAME');
assert.strictEqual(exported.device.model, 'GLOBAL_MODEL');
assert.strictEqual(exported.device.brand, 'GLOBAL_BRAND');

elements.autoBox.value = JSON.stringify([{
  accessToken: 'PASTED_AT_ONLY',
  realDeviceId: 'PASTED_REAL_DEVICE',
  storagePath: 'D:\\Trae\\storage.json'
}]);
run('state.accounts = [blankAccount()]');
run('autoParse()');
const parsed = run('buildConfig()');
assert.strictEqual(parsed.accounts[0].accessToken, 'PASTED_AT_ONLY');
assert.strictEqual(parsed.accounts[0].realDeviceId, 'PASTED_REAL_DEVICE');
assert.strictEqual(parsed.accounts[0].storagePath, 'D:\\Trae\\storage.json');

context.deviceOnlyConfig = { device: { name: 'DEVICE_ONLY' } };
run('applyConfigToForm(deviceOnlyConfig)');
const deviceOnly = run('buildConfig()');
assert.strictEqual(deviceOnly.accounts, undefined, 'device-only import kept stale accounts');
assert.strictEqual(deviceOnly.device.name, 'DEVICE_ONLY');

elements.importBox.value = 'IMPORT_BOX_SECRET';
elements.autoBox.value = 'AUTO_BOX_SECRET';
confirmAnswer = true;
run('resetForm()');
assert.strictEqual(elements.importBox.value, '', 'resetForm did not clear importBox');
assert.strictEqual(elements.autoBox.value, '', 'resetForm did not clear autoBox');

context.downloadAccount = {
  accessToken: 'DOWNLOAD_SECRET',
  deviceKeyPem: 'DOWNLOAD_KEY'
};
run('state.accounts = [accountFromRaw(downloadAccount)]');
confirmAnswer = false;
const beforeCancelClicks = context.clickCount;
const beforeCancelConfirms = context.confirmCount;
run('downloadJson()');
assert.strictEqual(context.clickCount, beforeCancelClicks, 'download proceeded after cancel');
assert.strictEqual(context.confirmCount, beforeCancelConfirms + 1);

confirmAnswer = true;
run('downloadJson()');
assert.strictEqual(context.clickCount, beforeCancelClicks + 1, 'confirmed download did not click');
assert.strictEqual(JSON.parse(lastBlobText).accounts[0].accessToken, 'DOWNLOAD_SECRET');

run('state.accounts = [blankAccount()]');
const beforeEmptyConfirms = context.confirmCount;
const beforeEmptyClicks = context.clickCount;
run('downloadJson()');
assert.strictEqual(context.confirmCount, beforeEmptyConfirms, 'empty config prompted unnecessarily');
assert.strictEqual(context.clickCount, beforeEmptyClicks + 1);

console.log('config builder harness: ok');
