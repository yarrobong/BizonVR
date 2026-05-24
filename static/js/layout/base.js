    let lucideRetryTimer = null;
    let pendingLucideRoot = null;
    let liveSearchStates = [];
    let liveSearchActiveState = null;
    let liveSearchDocumentListenersBound = false;
    let publicLayoutHtmxHandlersBound = false;
    let catalogScrollRestoreListenersBound = false;
    const liveSearchCache = new Map();
    const LIVE_SEARCH_MIN_QUERY_LENGTH = 2;
    const LIVE_SEARCH_MAX_QUERY_LENGTH = 80;
    const LIVE_SEARCH_DEBOUNCE_MS = 180;
    const LIVE_SEARCH_CACHE_LIMIT = 24;
    const LUCIDE_PENDING_ATTR = 'data-lucide-pending';
    const pageThresholdObservers = new Map();

    function getViewportHeight() {
      if (typeof window === 'undefined') {
        return 0;
      }
      return window.innerHeight || document.documentElement.clientHeight || 0;
    }

    function ensurePageThresholdObserver(rawOffset = 0) {
      const offset = Math.max(0, Number(rawOffset) || 0);
      const existingObserver = pageThresholdObservers.get(offset);
      if (existingObserver) {
        return existingObserver;
      }

      const sentinel = document.createElement('span');
      sentinel.setAttribute('aria-hidden', 'true');
      sentinel.setAttribute('data-page-threshold-sentinel', String(offset));
      Object.assign(sentinel.style, {
        position: 'absolute',
        top: `${offset}px`,
        left: '0',
        width: '1px',
        height: '1px',
        opacity: '0',
        pointerEvents: 'none',
      });

      const controller = {
        offset,
        listeners: new Set(),
        observer: null,
        fallbackHandler: null,
        lastState: false,
        hasEmitted: false,
        emit(nextState) {
          if (this.hasEmitted && this.lastState === nextState) {
            return;
          }
          this.lastState = nextState;
          this.hasEmitted = true;
          this.listeners.forEach((listener) => listener(nextState));
        },
        destroy() {
          if (this.observer) {
            this.observer.disconnect();
          }
          if (this.fallbackHandler) {
            window.removeEventListener('scroll', this.fallbackHandler);
            window.removeEventListener('resize', this.fallbackHandler);
          }
          if (sentinel.isConnected) {
            sentinel.remove();
          }
        },
      };

      if (document.body && !sentinel.isConnected) {
        document.body.appendChild(sentinel);
      }

      if (typeof IntersectionObserver === 'function') {
        controller.observer = new IntersectionObserver((entries) => {
          const entry = entries[0];
          controller.emit(!(entry && entry.isIntersecting));
        }, {
          threshold: 0,
        });
        controller.observer.observe(sentinel);
      } else {
        controller.fallbackHandler = () => {
          controller.emit(window.scrollY > offset);
        };
        window.addEventListener('scroll', controller.fallbackHandler, { passive: true });
        window.addEventListener('resize', controller.fallbackHandler);
      }

      controller.emit(window.scrollY > offset);
      pageThresholdObservers.set(offset, controller);
      return controller;
    }

    function observePageThreshold(offset, listener) {
      if (typeof window === 'undefined' || typeof document === 'undefined' || typeof listener !== 'function') {
        return () => {};
      }

      const controller = ensurePageThresholdObserver(offset);
      controller.listeners.add(listener);
      listener(controller.lastState);

      return () => {
        controller.listeners.delete(listener);
        if (controller.listeners.size > 0) {
          return;
        }
        controller.destroy();
        pageThresholdObservers.delete(controller.offset);
      };
    }

    function computeViewportVisibility(element, topOffset = 0, bottomOffset = 0) {
      if (!(element instanceof Element)) {
        return false;
      }

      const rect = element.getBoundingClientRect();
      const viewportHeight = getViewportHeight();
      return rect.bottom > topOffset && rect.top < (viewportHeight - bottomOffset);
    }

    function observeElementViewportState(element, callback, options = {}) {
      if (!(element instanceof Element) || typeof callback !== 'function') {
        return () => {};
      }

      const topOffset = Math.max(0, Number(options.topOffset) || 0);
      const bottomOffset = Math.max(0, Number(options.bottomOffset) || 0);
      const threshold = Array.isArray(options.threshold) || typeof options.threshold === 'number'
        ? options.threshold
        : 0;

      if (typeof IntersectionObserver === 'function') {
        const observer = new IntersectionObserver((entries) => {
          const entry = entries[0] || null;
          callback(Boolean(entry && entry.isIntersecting), entry);
        }, {
          threshold,
          rootMargin: `${-topOffset}px 0px ${-bottomOffset}px 0px`,
        });
        observer.observe(element);
        callback(computeViewportVisibility(element, topOffset, bottomOffset), null);
        return () => observer.disconnect();
      }

      const sync = () => {
        callback(computeViewportVisibility(element, topOffset, bottomOffset), null);
      };

      window.addEventListener('scroll', sync, { passive: true });
      window.addEventListener('resize', sync);
      sync();

      return () => {
        window.removeEventListener('scroll', sync);
        window.removeEventListener('resize', sync);
      };
    }

    function observeElementSize(element, callback) {
      if (!(element instanceof Element) || typeof callback !== 'function') {
        return () => {};
      }

      if (typeof ResizeObserver === 'function') {
        const observer = new ResizeObserver(() => {
          callback(element);
        });
        observer.observe(element);
        callback(element);
        return () => observer.disconnect();
      }

      const sync = () => callback(element);
      window.addEventListener('resize', sync);
      sync();

      return () => {
        window.removeEventListener('resize', sync);
      };
    }

    window.observePageThreshold = observePageThreshold;
    window.observeElementViewportState = observeElementViewportState;
    window.observeElementSize = observeElementSize;

    window.catalogProductList = window.catalogProductList || function catalogProductList() {
      return {
        filtersModalOpen: false,
        sortDropdownOpen: false,
        mobileFiltersDirty: false,
        pendingFiltersUrl: '',
        quickPriceTimer: null,

        init() {
          this.$nextTick(() => this.syncAllPriceRanges());
        },

        syncAllPriceRanges() {
          document.querySelectorAll('[data-filters-price]').forEach((el) => {
            this.syncPriceRange(el);
          });
        },

        normalizePriceInputs(formOrScope) {
          const scope = formOrScope?.matches?.('[data-filters-price]')
            ? formOrScope
            : formOrScope?.querySelector?.('[data-filters-price]');
          if (!scope) return;

          const minInput = scope.querySelector('input[name=price_min]');
          const maxInput = scope.querySelector('input[name=price_max]');
          if (!minInput || !maxInput) return;

          const minBound = Number(scope.dataset.min || 0);
          const maxBound = Number(scope.dataset.max || 0);
          const minValue = minInput.value === '' ? minBound : Number(minInput.value);
          const maxValue = maxInput.value === '' ? maxBound : Number(maxInput.value);

          if (Number.isFinite(minValue) && minValue <= minBound) {
            minInput.value = '';
          }
          if (Number.isFinite(maxValue) && maxValue >= maxBound) {
            maxInput.value = '';
          }
        },

        syncPriceRange(scope, source = '') {
          if (!scope) return;

          const minBound = Number(scope.dataset.min || 0);
          const maxBound = Number(scope.dataset.max || 0);
          if (!Number.isFinite(minBound) || !Number.isFinite(maxBound) || minBound >= maxBound) {
            return;
          }

          const minInput = scope.querySelector('input[name=price_min]');
          const maxInput = scope.querySelector('input[name=price_max]');
          const minRange = scope.querySelector('input[data-price-range=min]');
          const maxRange = scope.querySelector('input[data-price-range=max]');

          const parseValue = (value, fallback) => {
            if (value === '' || value === null || typeof value === 'undefined') return fallback;
            const parsed = Number(value);
            return Number.isFinite(parsed) ? parsed : fallback;
          };
          const clamp = (value, lower, upper) => Math.min(Math.max(value, lower), upper);

          const resolvePriceValue = (inputEl, rangeEl, bound, inputSource, rangeSource) => {
            if (source === rangeSource) {
              return parseValue(rangeEl?.value, parseValue(inputEl?.value, bound));
            }
            if (source === inputSource) {
              return parseValue(inputEl?.value, parseValue(rangeEl?.value, bound));
            }
            return parseValue(inputEl?.value, parseValue(rangeEl?.value, bound));
          };

          let minValue = resolvePriceValue(minInput, minRange, minBound, 'min-input', 'min-range');
          let maxValue = resolvePriceValue(maxInput, maxRange, maxBound, 'max-input', 'max-range');

          minValue = clamp(minValue, minBound, maxBound);
          maxValue = clamp(maxValue, minBound, maxBound);

          if (source === 'min-range' || source === 'min-input') {
            maxValue = Math.max(maxValue, minValue);
          } else if (source === 'max-range' || source === 'max-input') {
            minValue = Math.min(minValue, maxValue);
          } else if (minValue > maxValue) {
            minValue = minBound;
            maxValue = maxBound;
          }

          if (minRange) minRange.value = String(minValue);
          if (maxRange) maxRange.value = String(maxValue);
          if (minInput && source) minInput.value = minValue <= minBound ? '' : String(minValue);
          if (maxInput && source) maxInput.value = maxValue >= maxBound ? '' : String(maxValue);

          const formatPrice = (value) =>
            `${new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 }).format(Math.round(value))} ₽`;
          const minLabel = scope.querySelector('[data-price-current=min]');
          const maxLabel = scope.querySelector('[data-price-current=max]');
          if (minLabel) minLabel.textContent = formatPrice(minValue);
          if (maxLabel) maxLabel.textContent = formatPrice(maxValue);

          const total = maxBound - minBound;
          const minPercent = ((minValue - minBound) / total) * 100;
          const maxPercent = ((maxValue - minBound) / total) * 100;
          scope.style.setProperty('--price-min-percent', `${minPercent}%`);
          scope.style.setProperty('--price-max-percent', `${maxPercent}%`);
        },

        applyFilters(formId, scopeEl) {
          const form = document.getElementById(formId);
          if (!form) return;

          const base = this.pendingFiltersUrl || window.location.href;
          const url = new URL(base, window.location.origin);

          // Never keep pagination when filters change
          url.searchParams.delete('page');

          // Category/section come from the hidden form (pending values in defer-mode)
          const sectionVal = form.querySelector('input[name=section]')?.value ?? '';
          const categoryVal = form.querySelector('input[name=category]')?.value ?? '';

          if (sectionVal) url.searchParams.set('section', sectionVal);
          else url.searchParams.delete('section');

          if (categoryVal) url.searchParams.set('category', categoryVal);
          else url.searchParams.delete('category');

          // Price comes from visible inputs (if present in current filter UI)
          const scope = scopeEl || document;
          this.normalizePriceInputs(scope);
          const minVal = scope.querySelector('input[type=number][name=price_min]')?.value ?? '';
          const maxVal = scope.querySelector('input[type=number][name=price_max]')?.value ?? '';

          if (minVal) url.searchParams.set('price_min', minVal);
          else url.searchParams.delete('price_min');

          if (maxVal) url.searchParams.set('price_max', maxVal);
          else url.searchParams.delete('price_max');

          window.location.href = url.toString();
        },

        submitQuickPrice(form) {
          if (!form) return;
          if (this.quickPriceTimer) {
            clearTimeout(this.quickPriceTimer);
            this.quickPriceTimer = null;
          }
          this.normalizePriceInputs(form);
          form.requestSubmit();
        },

        queueQuickPriceSubmit(form) {
          if (!form) return;
          if (this.quickPriceTimer) {
            clearTimeout(this.quickPriceTimer);
            this.quickPriceTimer = null;
          }

          this.quickPriceTimer = window.setTimeout(() => {
            this.normalizePriceInputs(form);
            form.requestSubmit();
            this.quickPriceTimer = null;
          }, 650);
        },

        syncBodyOverflow() {
          const lock = this.filtersModalOpen && window.innerWidth < 1024;
          document.documentElement.classList.toggle('overflow-hidden', lock);
          document.body.classList.toggle('overflow-hidden', lock);
          if (!this.filtersModalOpen) {
            this.mobileFiltersDirty = false;
          }
        },
      };
    };

    function clearQueuedLucideInit() {
      if (lucideRetryTimer === null || typeof window === 'undefined') {
        return;
      }

      window.clearTimeout(lucideRetryTimer);
      lucideRetryTimer = null;
    }

    function isLucideScope(root) {
      return root === document || root instanceof Element || root instanceof DocumentFragment;
    }

    function normalizeLucideRoot(root) {
      if (isLucideScope(root)) {
        return root;
      }
      return document;
    }

    function mergeLucideRoots(currentRoot, nextRoot) {
      const normalizedNextRoot = normalizeLucideRoot(nextRoot);
      if (!currentRoot || currentRoot === normalizedNextRoot) {
        return normalizedNextRoot;
      }
      if (currentRoot === document || normalizedNextRoot === document) {
        return document;
      }
      if (currentRoot.contains?.(normalizedNextRoot)) {
        return currentRoot;
      }
      if (normalizedNextRoot.contains?.(currentRoot)) {
        return normalizedNextRoot;
      }
      return document;
    }

    function queueLucideInit(root = document, delay = 0) {
      if (typeof window === 'undefined') {
        return false;
      }

      pendingLucideRoot = mergeLucideRoots(pendingLucideRoot, root);
      if (lucideRetryTimer !== null) {
        return true;
      }

      lucideRetryTimer = window.setTimeout(() => {
        const rootToInit = pendingLucideRoot || document;
        pendingLucideRoot = null;
        lucideRetryTimer = null;
        initLucide(rootToInit, true);
      }, delay);

      return true;
    }

    function isLucidePlaceholder(node) {
      return node instanceof Element && node.matches('[data-lucide]:not(svg)');
    }

    function collectPendingLucidePlaceholders(root = document) {
      if (!isLucideScope(root)) {
        return [];
      }

      const normalizedRoot = normalizeLucideRoot(root);
      if (normalizedRoot === document) {
        return Array.from(document.querySelectorAll('[data-lucide]:not(svg)'));
      }

      const placeholders = [];
      if (isLucidePlaceholder(normalizedRoot)) {
        placeholders.push(normalizedRoot);
      }
      placeholders.push(...normalizedRoot.querySelectorAll('[data-lucide]:not(svg)'));
      return placeholders;
    }

    function markPendingLucidePlaceholders(root = document) {
      const placeholders = collectPendingLucidePlaceholders(root);
      placeholders.forEach((placeholder) => {
        placeholder.setAttribute(LUCIDE_PENDING_ATTR, placeholder.getAttribute('data-lucide') || '');
      });
      return placeholders.length;
    }

    function hasPendingLucideIcons(node) {
      return collectPendingLucidePlaceholders(node).length > 0;
    }

    // Инициализация Lucide иконок после загрузки HTMX контента
    function initLucide(rootOrRetry = document, fromRetry = false) {
      if (typeof window === 'undefined') {
        return false;
      }

      const root = typeof rootOrRetry === 'boolean' ? document : normalizeLucideRoot(rootOrRetry);
      const retry = typeof rootOrRetry === 'boolean' ? rootOrRetry : fromRetry;

      if (!window.lucide || typeof window.lucide.createIcons !== 'function') {
        if (!retry) {
          queueLucideInit(root, 120);
        }
        return false;
      }

      clearQueuedLucideInit();
      if (!markPendingLucidePlaceholders(root)) {
        return true;
      }

      window.lucide.createIcons({
        nameAttr: LUCIDE_PENDING_ATTR,
      });
      document.querySelectorAll(`svg[${LUCIDE_PENDING_ATTR}]`).forEach((icon) => {
        icon.removeAttribute(LUCIDE_PENDING_ATTR);
      });
      return true;
    }

    window.queueLucideInit = queueLucideInit;
    window.initLucide = initLucide;
    
    function scrollToTop() {
      document.documentElement.scrollTop = 0;
      document.body.scrollTop = 0;
      window.scrollTo({ top: 0, left: 0, behavior: 'auto' });
    }

    function getCurrentFullPath() {
      return `${window.location.pathname}${window.location.search}`;
    }

    function getFullPathFromUrl(url) {
      try {
        const parsed = new URL(url, window.location.origin);
        return `${parsed.pathname}${parsed.search}`;
      } catch (e) {
        return getCurrentFullPath();
      }
    }

    function isCatalogListPath(path) {
      return path.startsWith('/catalog/')
        && !path.startsWith('/catalog/product/')
        && !path.startsWith('/catalog/favorites')
        && !path.startsWith('/catalog/cart')
        && !path.startsWith('/catalog/set-city/');
    }

    function isCatalogProductPath(path) {
      return path.startsWith('/catalog/product/');
    }

    function normalizeLiveSearchQuery(value) {
      return String(value || '').trim().slice(0, LIVE_SEARCH_MAX_QUERY_LENGTH);
    }

    function setLiveSearchCache(cacheKey, payload) {
      if (liveSearchCache.has(cacheKey)) {
        liveSearchCache.delete(cacheKey);
      }
      liveSearchCache.set(cacheKey, payload);
      while (liveSearchCache.size > LIVE_SEARCH_CACHE_LIMIT) {
        const oldestKey = liveSearchCache.keys().next().value;
        if (!oldestKey) {
          break;
        }
        liveSearchCache.delete(oldestKey);
      }
    }

    function shouldRunLiveSearch(query) {
      return normalizeLiveSearchQuery(query).length >= LIVE_SEARCH_MIN_QUERY_LENGTH;
    }

    function escapeHtml(value) {
      return String(value || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
    }

    function getLiveSearchResultLinks(state) {
      if (!state?.panel) {
        return [];
      }
      return Array.from(state.panel.querySelectorAll('[data-live-search-result-link]'));
    }

    function closeLiveSearch(state) {
      if (!state?.panel) {
        return;
      }
      state.panel.classList.remove('is-open');
      state.panel.innerHTML = '';
      state.input.setAttribute('aria-expanded', 'false');
      state.activeIndex = -1;
      if (liveSearchActiveState === state) {
        liveSearchActiveState = null;
      }
    }

    function closeAllLiveSearch(exceptState = null) {
      liveSearchStates = liveSearchStates.filter((state) => state.form?.isConnected);
      liveSearchStates.forEach((state) => {
        if (state !== exceptState) {
          closeLiveSearch(state);
        }
      });
    }

    function setLiveSearchActiveResult(state, index) {
      const links = getLiveSearchResultLinks(state);
      if (!links.length) {
        state.activeIndex = -1;
        return;
      }

      const normalizedIndex = Math.max(0, Math.min(index, links.length - 1));
      state.activeIndex = normalizedIndex;
      links.forEach((link, linkIndex) => {
        const isActive = linkIndex === normalizedIndex;
        link.classList.toggle('is-active', isActive);
        if (isActive) {
          link.scrollIntoView({ block: 'nearest' });
        }
      });
    }

    function buildLiveSearchResultsUrl(state, query) {
      const url = new URL(state.form.action, window.location.origin);
      const formData = new FormData(state.form);
      formData.forEach((value, key) => {
        if (key === 'q') {
          return;
        }
        if (value === null || typeof value === 'undefined' || value === '') {
          return;
        }
        url.searchParams.set(key, value);
      });
      if (query) {
        url.searchParams.set('q', query);
      } else {
        url.searchParams.delete('q');
      }
      return `${url.pathname}${url.search}`;
    }

    function renderLiveSearchItem(item, index) {
      const mediaHtml = item.image_url
        ? `<img src="${escapeHtml(item.image_url)}" alt="" loading="lazy">`
        : `<span class="live-search-item-placeholder">${escapeHtml(item.badge || '')}</span>`;
      const subtitleHtml = item.subtitle
        ? `<div class="live-search-item-subtitle">${escapeHtml(item.subtitle)}</div>`
        : '';
      const metaParts = [];
      if (item.price_label) {
        metaParts.push(`<span class="live-search-item-price">${escapeHtml(item.price_label)}</span>`);
      }
      if (item.status_label) {
        metaParts.push(`<span class="live-search-item-status">${escapeHtml(item.status_label)}</span>`);
      }
      const metaHtml = metaParts.length
        ? `<div class="live-search-item-meta">${metaParts.join('')}</div>`
        : '';

      return `
        <a href="${escapeHtml(item.url)}" class="live-search-item" data-live-search-result-link data-live-search-index="${index}">
          <span class="live-search-item-media">${mediaHtml}</span>
          <span class="live-search-item-copy">
            <span class="live-search-item-topline">
              <span class="live-search-item-title">${escapeHtml(item.title)}</span>
              ${item.badge ? `<span class="live-search-item-badge">${escapeHtml(item.badge)}</span>` : ''}
            </span>
            ${subtitleHtml}
            ${metaHtml}
          </span>
        </a>
      `;
    }

    function renderLiveSearchGroup(title, items, offset) {
      if (!items.length) {
        return { html: '', nextOffset: offset };
      }
      const groupItemsHtml = items.map((item, index) => renderLiveSearchItem(item, offset + index)).join('');
      return {
        html: `
          <section class="live-search-group">
            <div class="live-search-group-title">${escapeHtml(title)}</div>
            <div>${groupItemsHtml}</div>
          </section>
        `,
        nextOffset: offset + items.length,
      };
    }

    function openLiveSearch(state) {
      if (!state?.panel) {
        return;
      }
      closeAllLiveSearch(state);
      state.panel.classList.add('is-open');
      state.input.setAttribute('aria-expanded', 'true');
      liveSearchActiveState = state;
    }

    function renderLiveSearchResults(state, payload) {
      const groups = payload?.groups || {};
      const products = Array.isArray(groups.products) ? groups.products : [];
      const bundles = Array.isArray(groups.bundles) ? groups.bundles : [];
      const variants = Array.isArray(groups.variants) ? groups.variants : [];
      let offset = 0;
      const renderedProducts = renderLiveSearchGroup('Товары', products, offset);
      offset = renderedProducts.nextOffset;
      const renderedBundles = renderLiveSearchGroup('Комплекты', bundles, offset);
      offset = renderedBundles.nextOffset;
      const renderedVariants = renderLiveSearchGroup('Варианты', variants, offset);
      const hasResults = Boolean(products.length || bundles.length || variants.length);
      const query = normalizeLiveSearchQuery(payload?.query || state.input.value);
      const footerHtml = hasResults
        ? `
          <div class="live-search-footer">
            <a href="${escapeHtml(buildLiveSearchResultsUrl(state, query))}" class="live-search-all-link">
              Показать все результаты
            </a>
          </div>
        `
        : '';
      const bodyHtml = hasResults
        ? `${renderedProducts.html}${renderedBundles.html}${renderedVariants.html}`
        : `<div class="live-search-empty">Ничего не найдено. Попробуйте другое название товара, комплекта или варианта.</div>`;

      state.panel.innerHTML = `
        <div class="live-search-panel-body">
          ${bodyHtml}
        </div>
        ${footerHtml}
      `;
      state.activeIndex = -1;
      openLiveSearch(state);
    }

    function requestLiveSearch(state, rawQuery) {
      const query = normalizeLiveSearchQuery(rawQuery);
      state.lastQuery = query;

      if (!shouldRunLiveSearch(query)) {
        if (state.abortController) {
          state.abortController.abort();
          state.abortController = null;
        }
        closeLiveSearch(state);
        return Promise.resolve();
      }

      const cacheKey = query.toLocaleLowerCase('ru-RU');
      if (liveSearchCache.has(cacheKey)) {
        renderLiveSearchResults(state, liveSearchCache.get(cacheKey));
        return Promise.resolve();
      }

      if (state.abortController) {
        state.abortController.abort();
      }

      state.requestToken += 1;
      const requestToken = state.requestToken;
      const requestUrl = new URL(state.url, window.location.origin);
      requestUrl.searchParams.set('q', query);
      state.abortController = new AbortController();

      return window.fetch(requestUrl.toString(), {
        headers: {
          'X-Requested-With': 'XMLHttpRequest',
        },
        signal: state.abortController.signal,
      })
        .then((response) => {
          if (!response.ok) {
            throw new Error(`Live search failed: ${response.status}`);
          }
          return response.json();
        })
        .then((payload) => {
          if (requestToken !== state.requestToken || query !== state.lastQuery) {
            return;
          }
          setLiveSearchCache(cacheKey, payload);
          renderLiveSearchResults(state, payload);
        })
        .catch((error) => {
          if (error.name !== 'AbortError') {
            window.console.error(error);
          }
        });
    }

    function scheduleLiveSearch(state, rawQuery) {
      if (state.timer) {
        window.clearTimeout(state.timer);
      }
      state.timer = window.setTimeout(() => {
        requestLiveSearch(state, rawQuery);
      }, LIVE_SEARCH_DEBOUNCE_MS);
    }

    function handleLiveSearchSubmit(state, event) {
      const links = getLiveSearchResultLinks(state);
      if (state.panel.classList.contains('is-open') && state.activeIndex >= 0 && links[state.activeIndex]) {
        event.preventDefault();
        window.location.href = links[state.activeIndex].href;
      }
    }

    function initLiveSearchDocumentListeners() {
      if (liveSearchDocumentListenersBound) {
        return;
      }
      liveSearchDocumentListenersBound = true;

      document.addEventListener('click', (event) => {
        const clickedInsideState = liveSearchStates.find((state) => state.form.contains(event.target) || state.panel.contains(event.target));
        if (!clickedInsideState) {
          closeAllLiveSearch();
        }
      });
    }

    function wireLiveSearch(root = document) {
      initLiveSearchDocumentListeners();
      root.querySelectorAll('[data-live-search-form]').forEach((form) => {
        if (form.dataset.liveSearchBound === '1') {
          return;
        }
        const input = form.querySelector('[data-live-search-input]');
        const url = form.dataset.liveSearchUrl;
        if (!input || !url) {
          return;
        }

        let panel = form.querySelector('[data-live-search-panel]');
        if (!panel) {
          panel = document.createElement('div');
          panel.className = 'live-search-panel';
          panel.dataset.liveSearchPanel = '1';
          form.appendChild(panel);
        }

        const panelId = `live-search-panel-${liveSearchStates.length + 1}`;
        panel.id = panelId;
        input.setAttribute('aria-controls', panelId);
        input.setAttribute('aria-expanded', 'false');
        input.setAttribute('aria-autocomplete', 'list');
        input.setAttribute('aria-haspopup', 'listbox');

        const state = {
          form,
          input,
          url,
          panel,
          timer: null,
          abortController: null,
          requestToken: 0,
          activeIndex: -1,
          lastQuery: '',
        };
        liveSearchStates.push(state);
        form.dataset.liveSearchBound = '1';

        input.addEventListener('focus', () => {
          liveSearchActiveState = state;
          if (shouldRunLiveSearch(input.value)) {
            requestLiveSearch(state, input.value);
          }
        });

        input.addEventListener('input', () => {
          liveSearchActiveState = state;
          scheduleLiveSearch(state, input.value);
        });

        input.addEventListener('keydown', (event) => {
          const links = getLiveSearchResultLinks(state);
          if (event.key === 'ArrowDown' && links.length) {
            event.preventDefault();
            setLiveSearchActiveResult(state, state.activeIndex + 1);
            return;
          }
          if (event.key === 'ArrowUp' && links.length) {
            event.preventDefault();
            const nextIndex = state.activeIndex <= 0 ? links.length - 1 : state.activeIndex - 1;
            setLiveSearchActiveResult(state, nextIndex);
            return;
          }
          if (event.key === 'Escape') {
            closeLiveSearch(state);
          }
        });

        form.addEventListener('submit', (event) => handleLiveSearchSubmit(state, event));

        panel.addEventListener('mousemove', (event) => {
          const link = event.target.closest('[data-live-search-result-link]');
          if (!link) {
            return;
          }
          const nextIndex = Number(link.dataset.liveSearchIndex || '-1');
          if (Number.isInteger(nextIndex) && nextIndex >= 0) {
            setLiveSearchActiveResult(state, nextIndex);
          }
        });
      });
    }

    function syncProductCardGalleryState(gallery, nextIndex) {
      if (!(gallery instanceof Element)) {
        return;
      }

      const images = Array.from(gallery.querySelectorAll('[data-product-card-image]'));
      const segments = Array.from(gallery.querySelectorAll('[data-product-card-segment]'));
      if (!images.length) {
        return;
      }

      const normalizedIndex = Math.max(0, Math.min(Number(nextIndex) || 0, images.length - 1));
      gallery.dataset.activeIndex = String(normalizedIndex);
      gallery.classList.remove('has-broken-active');

      images.forEach((image, index) => {
        image.classList.toggle('is-active', index === normalizedIndex);
      });
      segments.forEach((segment, index) => {
        segment.classList.toggle('is-active', index === normalizedIndex);
      });

      if (images[normalizedIndex]?.dataset.imageBroken === '1') {
        gallery.classList.add('has-broken-active');
      }
    }

    function syncProductCardGalleryFallback(gallery) {
      if (!(gallery instanceof Element)) {
        return;
      }

      const images = Array.from(gallery.querySelectorAll('[data-product-card-image]'));
      const placeholder = gallery.querySelector('[data-product-card-placeholder]');
      const activeIndex = Number(gallery.dataset.activeIndex || '0');
      const fallbackIndex = images.findIndex((image) => image.dataset.imageBroken !== '1');

      if (fallbackIndex >= 0) {
        if (images[activeIndex]?.dataset.imageBroken === '1' && activeIndex !== fallbackIndex) {
          syncProductCardGalleryState(gallery, fallbackIndex);
        } else if (images[activeIndex]?.dataset.imageBroken === '1') {
          gallery.classList.add('has-broken-active');
        } else {
          gallery.classList.remove('has-broken-active');
        }

        if (placeholder) {
          placeholder.classList.add('hidden');
          placeholder.classList.remove('flex');
        }
        return;
      }

      gallery.classList.add('has-broken-active');
      if (placeholder) {
        placeholder.classList.remove('hidden');
        placeholder.classList.add('flex');
      }
    }

    function initProductCardGalleries(root = document) {
      const scope = root instanceof Element || root instanceof Document ? root : document;
      scope.querySelectorAll('[data-product-card-gallery]').forEach((gallery) => {
        if (gallery.dataset.galleryBound === '1') {
          syncProductCardGalleryFallback(gallery);
          return;
        }

        const images = Array.from(gallery.querySelectorAll('[data-product-card-image]'));
        const segments = Array.from(gallery.querySelectorAll('[data-product-card-segment]'));
        gallery.dataset.galleryBound = '1';
        syncProductCardGalleryState(gallery, 0);

        images.forEach((image) => {
          if (image.dataset.galleryImageBound === '1') {
            return;
          }
          image.dataset.galleryImageBound = '1';
          image.addEventListener('error', () => {
            image.dataset.imageBroken = '1';
            syncProductCardGalleryFallback(gallery);
          });
          image.addEventListener('load', () => {
            delete image.dataset.imageBroken;
            syncProductCardGalleryFallback(gallery);
          });
        });

        if (!segments.length) {
          syncProductCardGalleryFallback(gallery);
          return;
        }

        gallery.addEventListener('mouseenter', () => {
          gallery.classList.add('is-hovering');
        });
        gallery.addEventListener('mouseleave', () => {
          gallery.classList.remove('is-hovering');
          syncProductCardGalleryState(gallery, 0);
          syncProductCardGalleryFallback(gallery);
        });
        gallery.addEventListener('mousemove', (event) => {
          const bounds = gallery.getBoundingClientRect();
          if (!bounds.width) {
            return;
          }
          const offsetX = Math.max(0, Math.min(event.clientX - bounds.left, bounds.width));
          const nextIndex = Math.min(
            images.length - 1,
            Math.floor((offsetX / bounds.width) * images.length)
          );
          syncProductCardGalleryState(gallery, nextIndex);
          syncProductCardGalleryFallback(gallery);
        });

        syncProductCardGalleryFallback(gallery);
      });
    }

    function initCookieConsentBanner() {
      const banner = document.getElementById('cookie-consent-banner');
      const acceptBtn = document.getElementById('cookie-consent-accept');
      if (!banner || !acceptBtn) return;

      const STORAGE_KEY = 'bizonvr_cookie_consent_v1';
      const hideBanner = () => {
        banner.classList.remove('is-visible');
        banner.setAttribute('aria-hidden', 'true');
      };
      const showBanner = () => {
        banner.setAttribute('aria-hidden', 'false');
        // Двойной RAF гарантирует отдельный кадр для скрытого состояния,
        // чтобы входная анимация не "съедалась" на первом рендере.
        banner.classList.remove('is-visible');
        requestAnimationFrame(() => {
          requestAnimationFrame(() => {
            banner.classList.add('is-visible');
          });
        });
      };

      let isAccepted = false;
      try {
        isAccepted = window.localStorage.getItem(STORAGE_KEY) === '1';
      } catch (e) {
        isAccepted = false;
      }

      if (isAccepted) hideBanner();
      else showBanner();

      if (acceptBtn.dataset.cookieConsentBound === '1') return;
      acceptBtn.addEventListener('click', () => {
        try {
          window.localStorage.setItem(STORAGE_KEY, '1');
        } catch (e) {
          // Если localStorage недоступен, просто скрываем плашку в текущем рендере.
        }
        hideBanner();
      });
      acceptBtn.dataset.cookieConsentBound = '1';
    }
    
    // Функция для обновления активной вкладки в мобильном меню
    function updateActiveDockItem() {
      const activeSection = document.body.dataset.activeSection || 'home';
      const dockItems = document.querySelectorAll('.mobile-dock .dock-item');
      
      // Убираем класс active у всех вкладок
      dockItems.forEach(item => item.classList.remove('active'));
      
      // Определяем, какой пункт меню должен быть активным.
      // Важно: сначала определяем по URL (строгий приоритет), и только если не получилось — fallback на data-active-section.
      const currentPath = window.location.pathname || '/';
      const normalizedPath = currentPath.endsWith('/') ? currentPath : `${currentPath}/`;

      function resolveSectionByPath(pathname) {
        if (pathname === '/') return 'home';
        if (pathname.startsWith('/catalog/favorites/')) return 'favorites';
        if (pathname.startsWith('/catalog/cart/')) return 'cart';
        if (pathname.startsWith('/accounts/profile/')) return 'profile';
        if (pathname.startsWith('/catalog/')) return 'catalog';
        return null;
      }

      function resolveSectionByHref(href) {
        if (href === '/') return 'home';
        if (href.includes('/catalog/favorites/')) return 'favorites';
        if (href.includes('/catalog/cart/')) return 'cart';
        if (href.includes('/accounts/profile/')) return 'profile';
        if (href.includes('/catalog/')) return 'catalog';
        return null;
      }

      const sectionByPath = resolveSectionByPath(normalizedPath);
      const targetSection = sectionByPath || activeSection;
      
      dockItems.forEach(item => {
        const href = item.getAttribute('href');
        const itemSection = resolveSectionByHref(href || '');
        if (itemSection && itemSection === targetSection) {
          item.classList.add('active');
        }
      });
    }

    function normalizePhoneDigits(value, hasBuiltInPrefix) {
      const stringValue = String(value || '');
      let digits = stringValue.replace(/\D/g, '');
      const normalizedValue = stringValue.replace(/\s+/g, '');

      if (hasBuiltInPrefix && normalizedValue.startsWith('+7')) {
        digits = digits.slice(1);
      } else if (digits.length === 11 && (digits[0] === '7' || digits[0] === '8')) {
        digits = digits.slice(1);
      }
      return digits.slice(0, 10);
    }

    function formatPhoneDigits(digits, hasExternalPrefix) {
      const areaCode = digits.slice(0, 3);
      const prefix = digits.slice(3, 6);
      const linePart1 = digits.slice(6, 8);
      const linePart2 = digits.slice(8, 10);

      if (hasExternalPrefix) {
        let formatted = areaCode;
        if (digits.length > 3) formatted += `) ${prefix}`;
        if (digits.length > 6) formatted += `-${linePart1}`;
        if (digits.length > 8) formatted += `-${linePart2}`;
        return formatted;
      }

      if (!digits) return '';

      let formatted = '+7';
      if (areaCode) formatted += ` (${areaCode}`;
      if (digits.length > 3) formatted += `) ${prefix}`;
      if (digits.length > 6) formatted += `-${linePart1}`;
      if (digits.length > 8) formatted += `-${linePart2}`;
      return formatted;
    }

    function getCaretPositionByDigits(formattedValue, digitsBeforeCaret, hasExternalPrefix) {
      if (digitsBeforeCaret <= 0) return 0;

      let seenDigits = 0;
      let skippedPrefixDigits = 0;
      for (let index = 0; index < formattedValue.length; index += 1) {
        if (/\d/.test(formattedValue[index])) {
          if (hasExternalPrefix && skippedPrefixDigits < 1) {
            skippedPrefixDigits += 1;
            continue;
          }
          seenDigits += 1;
          if (seenDigits >= digitsBeforeCaret) {
            return index + 1;
          }
        }
      }

      return formattedValue.length;
    }

    function initPhoneMasks(root) {
      const scope = root || document;
      const inputs = scope.querySelectorAll('.js-phone-mask');

      inputs.forEach(input => {
        const wrapper = input.closest('.phone-input-wrapper');
        const bracket = wrapper ? wrapper.querySelector('.phone-prefix-bracket') : null;
        const hasExternalPrefix = !wrapper;
        const hasBuiltInPrefix = !wrapper;
        const syncValue = preserveCaret => {
          const currentValue = input.value || '';
          const selectionStart = typeof input.selectionStart === 'number' ? input.selectionStart : currentValue.length;
          const digitsBeforeCaret = normalizePhoneDigits(currentValue.slice(0, selectionStart), hasBuiltInPrefix).length;
          const digits = normalizePhoneDigits(currentValue, hasBuiltInPrefix);
          const formattedValue = formatPhoneDigits(digits, Boolean(wrapper));

          if (currentValue !== formattedValue) {
            input.value = formattedValue;
          }

          if (bracket) {
            bracket.style.display = digits ? '' : 'none';
          }

          if (
            preserveCaret
            && document.activeElement === input
            && typeof input.setSelectionRange === 'function'
          ) {
            const caretPosition = getCaretPositionByDigits(formattedValue, digitsBeforeCaret, hasExternalPrefix);
            requestAnimationFrame(() => input.setSelectionRange(caretPosition, caretPosition));
          }
        };

        if (!input.dataset.phoneMaskBound) {
          input.addEventListener('input', () => syncValue(true));
          input.addEventListener('focus', () => syncValue(false));
          input.addEventListener('blur', () => syncValue(false));
          input.dataset.phoneMaskBound = '1';
        }

        syncValue(false);
      });
    }

    function initPublicFormSpamProtection(root) {
      const scope = root || document;
      const inputs = scope.querySelectorAll('input[data-form-started-at]');

      inputs.forEach(input => {
        if (!input || input.value) {
          return;
        }
        input.value = String(Date.now());
      });
    }
    
    function initHtmxHandlers() {
      function syncLayoutState() {
        const mainContent = document.getElementById('main-content');
        const stickyHeaderMarker = mainContent?.querySelector('[data-layout-sticky-header]');
        const stickyHeaderEnabled = stickyHeaderMarker?.dataset.layoutStickyHeader !== 'off';

        window.dispatchEvent(new CustomEvent('layout-sticky-header', {
          detail: { enabled: stickyHeaderEnabled }
        }));
      }

      if (hasPendingLucideIcons(document)) {
        initLucide(document);
      }
      initPublicFormSpamProtection(document);
      initPhoneMasks(document);
      wireLiveSearch(document);
      initProductCardGalleries(document);
      initCookieConsentBanner();
      syncLayoutState();

      if (!document.body) {
        console.warn('document.body is not available yet');
        return;
      }

      if (publicLayoutHtmxHandlersBound || document.body.dataset.publicLayoutHtmxHandlersBound === '1') {
        updateActiveDockItem();
        return;
      }
      publicLayoutHtmxHandlersBound = true;
      document.body.dataset.publicLayoutHtmxHandlersBound = '1';

      document.body.addEventListener('htmx:beforeRequest', function(ev) {
        if (ev.detail.target?.id !== 'main-content') return;

        window.dispatchEvent(new CustomEvent('layout-close-overlays'));

        const mainContent = document.getElementById('main-content');
        if (!mainContent) return;

        mainContent.style.minHeight = `${Math.ceil(mainContent.getBoundingClientRect().height)}px`;
      });

      document.body.addEventListener('htmx:afterRequest', function(ev) {
        if (ev.detail.target?.id !== 'main-content' || ev.detail.successful) return;

        const mainContent = document.getElementById('main-content');
        if (mainContent) {
          mainContent.style.minHeight = '';
        }
      });
      
      document.body.addEventListener('htmx:beforeSwap', function(ev) {
        // Обновляем data-active-section перед заменой контента
        if (ev.detail.target.id === 'main-content') {
          const parser = new DOMParser();
          const doc = parser.parseFromString(ev.detail.xhr.responseText, 'text/html');
          const activeSectionMarker = doc.querySelector('#htmx-active-section');
          const newActiveSection = activeSectionMarker?.dataset?.section || doc.body.dataset.activeSection;
          if (newActiveSection) {
            document.body.dataset.activeSection = newActiveSection;
          }

          const sourcePath = getCurrentFullPath();
          const destinationPath = ev.detail?.xhr?.responseURL
            ? getFullPathFromUrl(ev.detail.xhr.responseURL)
            : sourcePath;
          const isCatalogReturn = isCatalogProductPath(sourcePath) && isCatalogListPath(destinationPath);

          if (!isCatalogReturn) {
            scrollToTop();
          }
        }
      });
      document.body.addEventListener('htmx:afterSettle', function(ev) {
        initPhoneMasks(document);
        // После полного обновления DOM
        if (ev.detail.target.id === 'main-content') {
          syncLayoutState();
          window.dispatchEvent(new CustomEvent('header-expand'));
          const mainContent = document.getElementById('main-content');
          if (mainContent) {
            mainContent.style.minHeight = '';
          }
          wireLiveSearch(document);
          initProductCardGalleries(document);
          // Обновляем активную вкладку в мобильном меню
          updateActiveDockItem();
        }
        // Manager portal: scroll to top after navigation
        if (ev.detail.target.id === 'manager-main-content') {
          scrollToTop();
        }
      });
      document.body.addEventListener('htmx:afterSwap', function(ev) {
        const swapTarget = ev.detail?.target || document;

        if (hasPendingLucideIcons(swapTarget)) {
          queueLucideInit(swapTarget, 0);
        }

        if (swapTarget?.id === 'main-content') {
          // НЕ скроллим вверх автоматически - позицию восстановит скрипт ниже
          // Alpine.js сам подхватит новые элементы с x-data
          // Поэтому initTree вызывать не обязательно и это может вызвать ошибки
          syncLayoutState();
          initPublicFormSpamProtection(document);
          initPhoneMasks(document);
          wireLiveSearch(document);
        }
        initPublicFormSpamProtection(swapTarget);
        initProductCardGalleries(swapTarget);
      });
      
      // Обновляем активную вкладку при первой загрузке
      updateActiveDockItem();
    }
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', initHtmxHandlers);
    } else {
      initHtmxHandlers();
    }

    // Сохраняем скролл только для сценария:
    // список каталога -> карточка товара -> возврат в тот же список.
    (function() {
      const STORAGE_KEY = 'bizonvr_catalog_list_return_scroll';
      let pendingNavigation = null;

      function saveCatalogListScroll(path) {
        try {
          if (!isCatalogListPath(path)) return;
          const payload = {
            path,
            scrollY: window.scrollY
          };
          sessionStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
        } catch (e) {
          console.warn('Failed to save scroll position:', e);
        }
      }

      function restoreCatalogListScroll(destinationPath, sourcePath) {
        try {
          const raw = sessionStorage.getItem(STORAGE_KEY);
          if (!raw) return;
          const saved = JSON.parse(raw);
          if (!saved || typeof saved.path !== 'string') return;
          if (!isCatalogProductPath(sourcePath || '')) return;
          if (destinationPath !== saved.path) return;
          if (typeof saved.scrollY !== 'number' || saved.scrollY <= 0) return;

          requestAnimationFrame(() => {
            requestAnimationFrame(() => {
              window.scrollTo(0, saved.scrollY);
            });
          });
        } catch (e) {
          console.warn('Failed to restore scroll position:', e);
        }
      }

      function initScrollRestoreListeners() {
        if (!document.body || catalogScrollRestoreListenersBound || document.body.dataset.catalogScrollRestoreListenersBound === '1') {
          return;
        }
        catalogScrollRestoreListenersBound = true;
        document.body.dataset.catalogScrollRestoreListenersBound = '1';

        document.body.addEventListener('htmx:beforeRequest', (ev) => {
          if (ev.detail.target?.id !== 'main-content') return;

          const sourcePath = getCurrentFullPath();
          const destinationPath = ev.detail?.pathInfo?.requestPath
            ? getFullPathFromUrl(ev.detail.pathInfo.requestPath)
            : null;

          if (isCatalogListPath(sourcePath) && isCatalogProductPath(destinationPath || '')) {
            saveCatalogListScroll(sourcePath);
          }

          pendingNavigation = {
            fromPath: sourcePath
          };
        });

        document.body.addEventListener('htmx:afterSettle', (ev) => {
          if (ev.detail.target.id === 'main-content') {
            const destinationPath = ev.detail?.xhr?.responseURL
              ? getFullPathFromUrl(ev.detail.xhr.responseURL)
              : getCurrentFullPath();
            const sourcePath = pendingNavigation?.fromPath || null;
            pendingNavigation = null;

            restoreCatalogListScroll(destinationPath, sourcePath);
          }
        });
      }

      if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => {
          initScrollRestoreListeners();
        });
      } else {
        initScrollRestoreListeners();
      }
    })();
