(function (root, factory) {
  const exports = factory(root);

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = exports;
  }

  if (root) {
    root.BizonVRMetrika = Object.assign({}, root.BizonVRMetrika, exports);
    if (root.document) {
      exports.init();
    }
  }
})(typeof window !== 'undefined' ? window : globalThis, function (root) {
  const COUNTER_ID = 108292006;

  function getLocationHref(runtimeRoot) {
    return runtimeRoot && runtimeRoot.location && typeof runtimeRoot.location.href === 'string'
      ? runtimeRoot.location.href
      : '';
  }

  function shouldTrackVirtualHit(targetId, lastTrackedUrl, nextUrl) {
    return targetId === 'main-content' && Boolean(nextUrl) && nextUrl !== lastTrackedUrl;
  }

  function buildHitOptions(referrer) {
    return referrer ? { referer: referrer } : {};
  }

  function sendVirtualHit(runtimeRoot, nextUrl, referrer) {
    if (!runtimeRoot || typeof runtimeRoot.ym !== 'function' || !nextUrl) {
      return false;
    }

    runtimeRoot.ym(COUNTER_ID, 'hit', nextUrl, buildHitOptions(referrer));
    return true;
  }

  function createTracker(runtimeRoot) {
    let lastTrackedUrl = getLocationHref(runtimeRoot);
    let pendingReferrer = null;
    let bound = false;

    function handleBeforeRequest(event) {
      if (event && event.detail && event.detail.target && event.detail.target.id === 'main-content') {
        pendingReferrer = getLocationHref(runtimeRoot);
      }
    }

    function handleAfterSettle(event) {
      const targetId = event && event.detail && event.detail.target ? event.detail.target.id : null;
      const nextUrl = getLocationHref(runtimeRoot);

      if (!shouldTrackVirtualHit(targetId, lastTrackedUrl, nextUrl)) {
        if (targetId === 'main-content') {
          pendingReferrer = null;
        }
        return false;
      }

      const referrer = pendingReferrer || lastTrackedUrl;
      const tracked = sendVirtualHit(runtimeRoot, nextUrl, referrer);
      pendingReferrer = null;

      if (tracked) {
        lastTrackedUrl = nextUrl;
      }

      return tracked;
    }

    function bind() {
      if (
        bound
        || !runtimeRoot
        || !runtimeRoot.document
        || !runtimeRoot.document.body
        || typeof runtimeRoot.document.body.addEventListener !== 'function'
      ) {
        return false;
      }

      runtimeRoot.document.body.addEventListener('htmx:beforeRequest', handleBeforeRequest);
      runtimeRoot.document.body.addEventListener('htmx:afterSettle', handleAfterSettle);
      bound = true;
      return true;
    }

    return {
      bind,
      handleBeforeRequest,
      handleAfterSettle,
      getLastTrackedUrl() {
        return lastTrackedUrl;
      },
      getPendingReferrer() {
        return pendingReferrer;
      },
    };
  }

  function init() {
    if (!root || !root.document) {
      return null;
    }

    if (root.__bizonvrMetrikaTracker) {
      return root.__bizonvrMetrikaTracker;
    }

    const tracker = createTracker(root);
    root.__bizonvrMetrikaTracker = tracker;

    if (root.document.readyState === 'loading' && typeof root.document.addEventListener === 'function') {
      root.document.addEventListener('DOMContentLoaded', function onDomReady() {
        tracker.bind();
      }, { once: true });
    } else {
      tracker.bind();
    }

    return tracker;
  }

  return {
    COUNTER_ID,
    buildHitOptions,
    createTracker,
    init,
    sendVirtualHit,
    shouldTrackVirtualHit,
  };
});
