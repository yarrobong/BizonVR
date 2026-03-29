const test = require('node:test');
const assert = require('node:assert/strict');

const {
  COUNTER_ID,
  createTracker,
  shouldTrackVirtualHit,
} = require('./metrika.js');

function makeRuntime(initialUrl = 'https://bizonvr.ru/') {
  const listeners = {};
  const ymCalls = [];

  return {
    listeners,
    ymCalls,
    location: { href: initialUrl },
    ym(...args) {
      ymCalls.push(args);
    },
    document: {
      readyState: 'complete',
      body: {
        addEventListener(name, handler) {
          listeners[name] = handler;
        },
      },
      addEventListener() {},
    },
  };
}

test('initial tracker bind does not send a virtual hit on first load', () => {
  const runtime = makeRuntime();
  const tracker = createTracker(runtime);

  assert.equal(tracker.bind(), true);
  assert.equal(runtime.ymCalls.length, 0);
  assert.equal(tracker.getLastTrackedUrl(), 'https://bizonvr.ru/');
});

test('htmx navigation to a new public URL sends exactly one Yandex hit with referrer', () => {
  const runtime = makeRuntime('https://bizonvr.ru/catalog/');
  const tracker = createTracker(runtime);
  tracker.bind();

  runtime.listeners['htmx:beforeRequest']({
    detail: {
      target: { id: 'main-content' },
    },
  });
  runtime.location.href = 'https://bizonvr.ru/catalog/?page=2';

  runtime.listeners['htmx:afterSettle']({
    detail: {
      target: { id: 'main-content' },
    },
  });

  assert.equal(runtime.ymCalls.length, 1);
  assert.deepEqual(runtime.ymCalls[0], [
    COUNTER_ID,
    'hit',
    'https://bizonvr.ru/catalog/?page=2',
    { referer: 'https://bizonvr.ru/catalog/' },
  ]);
  assert.equal(tracker.getLastTrackedUrl(), 'https://bizonvr.ru/catalog/?page=2');
});

test('repeated settle without URL change does not duplicate the hit', () => {
  const runtime = makeRuntime('https://bizonvr.ru/catalog/');
  const tracker = createTracker(runtime);
  tracker.bind();

  runtime.listeners['htmx:beforeRequest']({
    detail: {
      target: { id: 'main-content' },
    },
  });
  runtime.location.href = 'https://bizonvr.ru/catalog/?page=2';
  runtime.listeners['htmx:afterSettle']({
    detail: {
      target: { id: 'main-content' },
    },
  });
  runtime.listeners['htmx:afterSettle']({
    detail: {
      target: { id: 'main-content' },
    },
  });

  assert.equal(runtime.ymCalls.length, 1);
});

test('virtual hit tracking ignores non-main-content targets', () => {
  assert.equal(
    shouldTrackVirtualHit('manager-main-content', 'https://bizonvr.ru/catalog/', 'https://bizonvr.ru/catalog/?page=2'),
    false,
  );
});
