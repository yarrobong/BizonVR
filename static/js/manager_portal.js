(function () {
  const FILTER_DEBOUNCE_MS = 260;
  const GLOBAL_SEARCH_DEBOUNCE_MS = 180;
  const CHART_JS_URL = window.managerPortalShell?.chartJsUrl || '/static/vendor/chartjs/chart-4.4.8.umd.min.js';
  const TABLE_SORT_STORAGE_PREFIX = 'manager-portal-table-sort:';
  const MANAGER_PROGRESS_PENDING_KEY = window.managerPortalProgress?.pendingKey || 'manager-portal:navigation-pending';
  const MANAGER_SIDEBAR_COLLAPSED_KEY = window.managerPortalShell?.sidebarCollapsedKey || 'manager-portal:sidebar-collapsed';
  const MANAGER_THEME_STORAGE_KEY = window.managerPortalTheme?.storageKey || 'manager-portal:theme';
  const MANAGER_DEFAULT_THEME = window.managerPortalTheme?.defaultTheme || 'light';
  let filterTimers = new WeakMap();
  let globalSearchState = null;
  let globalSearchStates = [];
  let chartJsPromise = null;
  let navigationProgressArmed = false;
  let managerTheme = normalizeTheme(document.documentElement.dataset.managerTheme || MANAGER_DEFAULT_THEME);
  const sortCollator = new Intl.Collator('ru', {numeric: true, sensitivity: 'base'});

  function getCookie(name) {
    const cookies = document.cookie ? document.cookie.split(';') : [];
    for (const cookie of cookies) {
      const trimmed = cookie.trim();
      if (trimmed.startsWith(`${name}=`)) {
        return decodeURIComponent(trimmed.slice(name.length + 1));
      }
    }
    return '';
  }

  function isEditableTarget(target) {
    if (!target) {
      return false;
    }
    const tagName = target.tagName;
    return Boolean(
      target.isContentEditable
      || tagName === 'INPUT'
      || tagName === 'TEXTAREA'
      || tagName === 'SELECT'
    );
  }

  function isRunnableSearchQuery(query) {
    return query.length >= 2 || /^\d+$/.test(query);
  }

  function normalizeTheme(value) {
    return value === 'dark' ? 'dark' : 'light';
  }

  function getManagerStorage() {
    try {
      return window.localStorage;
    } catch (error) {
      return null;
    }
  }

  function updateThemeToggleButtons() {
    document.querySelectorAll('[data-manager-theme-option]').forEach((button) => {
      const isActive = button.dataset.managerThemeOption === managerTheme;
      button.classList.toggle('is-active', isActive);
      button.setAttribute('aria-pressed', isActive ? 'true' : 'false');
    });
  }

  function applyManagerTheme(theme, {persist = true} = {}) {
    managerTheme = normalizeTheme(theme);
    document.documentElement.dataset.managerTheme = managerTheme;
    document.documentElement.style.colorScheme = managerTheme;
    updateThemeToggleButtons();
    if (!persist) {
      return;
    }
    const storage = getManagerStorage();
    if (!storage) {
      return;
    }
    try {
      storage.setItem(MANAGER_THEME_STORAGE_KEY, managerTheme);
    } catch (error) {
      window.console.warn('Unable to persist manager theme preference.', error);
    }
  }

  function wireThemeToggle(root) {
    if (!root || typeof root.querySelectorAll !== 'function') {
      updateThemeToggleButtons();
      return;
    }
    root.querySelectorAll('[data-manager-theme-toggle]').forEach((toggle) => {
      if (toggle.dataset.themeBound === '1') {
        return;
      }
      toggle.dataset.themeBound = '1';
      toggle.querySelectorAll('[data-manager-theme-option]').forEach((button) => {
        button.addEventListener('click', () => {
          applyManagerTheme(button.dataset.managerThemeOption);
        });
      });
    });
    updateThemeToggleButtons();
  }

  function hasNavigationProgress() {
    return Boolean(window.NProgress && typeof window.NProgress.start === 'function' && typeof window.NProgress.done === 'function');
  }

  function persistNavigationProgressPending() {
    try {
      window.sessionStorage.setItem(MANAGER_PROGRESS_PENDING_KEY, '1');
    } catch (error) {
      window.console.warn('Unable to persist manager navigation progress state.', error);
    }
  }

  function clearNavigationProgressPending() {
    try {
      window.sessionStorage.removeItem(MANAGER_PROGRESS_PENDING_KEY);
    } catch (error) {
      window.console.warn('Unable to clear manager navigation progress state.', error);
    }
  }

  function startNavigationProgress() {
    if (!hasNavigationProgress() || navigationProgressArmed) {
      return;
    }
    navigationProgressArmed = true;
    persistNavigationProgressPending();
    window.NProgress.start();
  }

  function completeNavigationProgress() {
    navigationProgressArmed = false;
    clearNavigationProgressPending();
    if (!hasNavigationProgress()) {
      return;
    }
    window.NProgress.done();
  }

  function isModifiedNavigation(event) {
    return event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0;
  }

  function isPageAnchorLink(url) {
    return url.origin === window.location.origin
      && url.pathname === window.location.pathname
      && url.search === window.location.search
      && url.hash;
  }

  function elementHasHtmxBehavior(element) {
    if (!element) {
      return false;
    }
    return Array.from(element.attributes).some((attribute) => attribute.name === 'hx-boost' || attribute.name.startsWith('hx-'));
  }

  function shouldTrackNavigationLink(link, event) {
    if (!link || event.defaultPrevented || isModifiedNavigation(event)) {
      return false;
    }
    const href = link.getAttribute('href');
    if (!href || href.startsWith('javascript:') || href === '#') {
      return false;
    }
    if (
      link.hasAttribute('download')
      || (link.target && link.target !== '_self')
      || link.dataset.noProgress === 'true'
      || elementHasHtmxBehavior(link)
    ) {
      return false;
    }
    let url;
    try {
      url = new URL(link.href, window.location.href);
    } catch (error) {
      return false;
    }
    if (!['http:', 'https:'].includes(url.protocol)) {
      return false;
    }
    if (url.origin !== window.location.origin) {
      return false;
    }
    if (isPageAnchorLink(url)) {
      return false;
    }
    return true;
  }

  function shouldTrackNavigationForm(form) {
    if (
      !form
      || form.dataset.noProgress === 'true'
      || elementHasHtmxBehavior(form)
      || (form.target && form.target !== '_self')
    ) {
      return false;
    }
    const method = (form.getAttribute('method') || 'get').toLowerCase();
    return ['get', 'post'].includes(method);
  }

  function isDesktopViewport() {
    return window.matchMedia('(min-width: 1024px)').matches;
  }

  function readSidebarCollapsedPreference() {
    try {
      return window.localStorage.getItem(MANAGER_SIDEBAR_COLLAPSED_KEY) === '1';
    } catch (error) {
      return document.documentElement.classList.contains('manager-sidebar-collapsed');
    }
  }

  function writeSidebarCollapsedPreference(collapsed) {
    try {
      if (collapsed) {
        window.localStorage.setItem(MANAGER_SIDEBAR_COLLAPSED_KEY, '1');
      } else {
        window.localStorage.removeItem(MANAGER_SIDEBAR_COLLAPSED_KEY);
      }
    } catch (error) {
      // Ignore storage write failures and keep the current DOM state.
    }
  }

  function syncDesktopSidebarToggleState() {
    const collapsed = document.documentElement.classList.contains('manager-sidebar-collapsed');
    document.querySelectorAll('[data-manager-sidebar-toggle]').forEach((button) => {
      button.setAttribute('aria-pressed', collapsed ? 'true' : 'false');
      const label = button.querySelector('[data-manager-sidebar-toggle-label]');
      const expandedLabel = label?.dataset.expandedLabel || 'Свернуть';
      const collapsedLabel = label?.dataset.collapsedLabel || 'Развернуть';
      if (label) {
        label.textContent = collapsed ? collapsedLabel : expandedLabel;
      }
      const actionLabel = collapsed ? 'Развернуть меню' : 'Свернуть меню';
      button.setAttribute('aria-label', actionLabel);
      button.setAttribute('title', actionLabel);
    });
  }

  function setDesktopSidebarCollapsed(collapsed, {persist = true} = {}) {
    document.documentElement.classList.toggle('manager-sidebar-collapsed', collapsed);
    if (persist) {
      writeSidebarCollapsedPreference(collapsed);
    }
    syncDesktopSidebarToggleState();
  }

  function wireNavigationProgress() {
    if (document.body.dataset.managerNavigationProgressBound === '1') {
      return;
    }
    document.body.dataset.managerNavigationProgressBound = '1';

    document.addEventListener('click', (event) => {
      const link = event.target.closest('a');
      if (!shouldTrackNavigationLink(link, event)) {
        return;
      }
      startNavigationProgress();
    }, true);

    document.addEventListener('submit', (event) => {
      const form = event.target;
      if (!(form instanceof HTMLFormElement) || !shouldTrackNavigationForm(form)) {
        return;
      }
      startNavigationProgress();
    }, true);
  }

  function wireDesktopSidebar(root) {
    root.querySelectorAll('[data-manager-sidebar-toggle]').forEach((button) => {
      if (button.dataset.managerBound === '1') {
        return;
      }
      button.dataset.managerBound = '1';
      button.addEventListener('click', () => {
        if (!isDesktopViewport()) {
          return;
        }
        const isCollapsed = document.documentElement.classList.contains('manager-sidebar-collapsed');
        setDesktopSidebarCollapsed(!isCollapsed);
      });
    });

    if (isDesktopViewport()) {
      setDesktopSidebarCollapsed(readSidebarCollapsedPreference(), {persist: false});
    } else {
      syncDesktopSidebarToggleState();
    }
  }

  function syncClientFiltersState(root, isOpen) {
    root.dataset.clientFiltersOpen = isOpen ? 'true' : 'false';
    const toggle = root.querySelector('[data-client-filters-toggle]');
    const panel = root.querySelector('[data-client-filters-panel]');
    if (toggle) {
      const label = isOpen ? 'Свернуть фильтры' : 'Развернуть фильтры';
      toggle.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
      toggle.setAttribute('aria-label', label);
      toggle.setAttribute('title', label);
    }
    if (panel) {
      panel.setAttribute('aria-hidden', isOpen ? 'false' : 'true');
    }
  }

  function wireClientFilters(root) {
    const filterRoots = root.matches?.('[data-client-filters-root]')
      ? [root]
      : root.querySelectorAll('[data-client-filters-root]');

    filterRoots.forEach((filtersRoot) => {
      if (filtersRoot.dataset.clientFiltersBound === '1') {
        return;
      }
      filtersRoot.dataset.clientFiltersBound = '1';
      const toggle = filtersRoot.querySelector('[data-client-filters-toggle]');
      if (!toggle) {
        return;
      }
      syncClientFiltersState(filtersRoot, false);
      toggle.addEventListener('click', () => {
        const isOpen = filtersRoot.dataset.clientFiltersOpen === 'true';
        syncClientFiltersState(filtersRoot, !isOpen);
      });
    });
  }

  function syncResponsivePlaceholder(input) {
    if (!input) {
      return;
    }
    if (!input.dataset.desktopPlaceholder) {
      input.dataset.desktopPlaceholder = input.getAttribute('placeholder') || '';
    }
    const mobilePlaceholder = input.dataset.mobilePlaceholder;
    const desktopPlaceholder = input.dataset.desktopPlaceholder;
    if (mobilePlaceholder && window.matchMedia('(max-width: 767px)').matches) {
      input.setAttribute('placeholder', mobilePlaceholder);
      return;
    }
    input.setAttribute('placeholder', desktopPlaceholder);
  }

  function isSearchStateVisible(state) {
    return Boolean(state && state.root && state.root.isConnected && state.root.offsetParent !== null);
  }

  function getSearchState(predicate) {
    return globalSearchStates.find((state) => state.root && state.root.isConnected && predicate(state)) || null;
  }

  function getPreferredSearchState({ preferOverlay = false } = {}) {
    const visibleStates = globalSearchStates.filter(isSearchStateVisible);
    if (preferOverlay) {
      return visibleStates.find((state) => state.root.hasAttribute('data-overlay-search-root'))
        || getSearchState((state) => state.root.hasAttribute('data-overlay-search-root'));
    }
    return visibleStates.find((state) => !state.root.hasAttribute('data-overlay-search-root'))
      || visibleStates[0]
      || globalSearchStates.find((state) => !state.root.hasAttribute('data-overlay-search-root'))
      || globalSearchStates[0]
      || null;
  }

  function getSearchResultLinks(state) {
    return Array.from(state.panel.querySelectorAll('[data-manager-search-result-link]'));
  }

  function syncGlobalSearchActiveResult(state, nextIndex) {
    const links = getSearchResultLinks(state);
    if (!links.length) {
      state.activeIndex = -1;
      return;
    }
    state.activeIndex = nextIndex < 0 ? -1 : Math.max(0, Math.min(nextIndex, links.length - 1));
    links.forEach((link, index) => {
      const isActive = index === state.activeIndex;
      link.classList.toggle('is-active', isActive);
      if (isActive) {
        link.scrollIntoView({ block: 'nearest' });
      }
    });
  }

  function openGlobalSearch(state) {
    globalSearchState = state;
    state.panel.classList.remove('hidden');
    state.input.setAttribute('aria-expanded', 'true');
    if (state.backdrop) {
      state.backdrop.classList.remove('hidden');
    }
  }

  function closeGlobalSearch(state) {
    if (!state) {
      return;
    }
    if (state.timer) {
      window.clearTimeout(state.timer);
      state.timer = null;
    }
    if (state.abortController) {
      state.abortController.abort();
      state.abortController = null;
    }
    state.panel.classList.add('hidden');
    state.input.setAttribute('aria-expanded', 'false');
    syncGlobalSearchActiveResult(state, -1);
    if (state.backdrop) {
      state.backdrop.classList.add('hidden');
    }
    if (globalSearchState === state) {
      globalSearchState = null;
    }
  }

  function focusGlobalSearchInput() {
    const state = isSearchStateVisible(globalSearchState) ? globalSearchState : getPreferredSearchState();
    if (state && state.root.hasAttribute('data-overlay-search-root') && !isSearchStateVisible(state)) {
      if (openGlobalSearchOverlay()) {
        return;
      }
    }
    if (!state) {
      openGlobalSearchOverlay();
      return;
    }
    globalSearchState = state;
    state.input.focus();
    state.input.select();
    requestGlobalSearch(state, state.input.value.trim());
  }

  function openGlobalSearchOverlay() {
    const overlay = document.querySelector('[data-global-search-overlay]');
    if (!overlay) {
      return false;
    }
    overlay.classList.remove('hidden');
    overlay.setAttribute('aria-hidden', 'false');
    document.documentElement.style.overflow = 'hidden';
    const state = getPreferredSearchState({ preferOverlay: true });
    if (!state) {
      return true;
    }
    window.requestAnimationFrame(() => {
      globalSearchState = state;
      state.input.focus();
      state.input.select();
      requestGlobalSearch(state, state.input.value.trim());
    });
    return true;
  }

  function closeGlobalSearchOverlay() {
    const overlay = document.querySelector('[data-global-search-overlay]');
    if (!overlay || overlay.classList.contains('hidden')) {
      return;
    }
    const state = getSearchState((item) => overlay.contains(item.root));
    if (state) {
      closeGlobalSearch(state);
    }
    overlay.classList.add('hidden');
    overlay.setAttribute('aria-hidden', 'true');
    if (!document.querySelector('.manager-drawer.is-open, .manager-mobile-sidebar.is-open')) {
      document.documentElement.style.overflow = '';
    }
  }

  function requestGlobalSearch(state, rawQuery) {
    const query = String(rawQuery || '').trim();
    const effectiveQuery = isRunnableSearchQuery(query) ? query : '';
    const url = state.form.dataset.managerGlobalSearchUrl;
    if (!url) {
      return Promise.resolve();
    }
    if (state.abortController) {
      state.abortController.abort();
    }
    state.requestToken += 1;
    const requestToken = state.requestToken;
    state.abortController = new AbortController();
    state.lastQuery = query;
    state.isLoading = true;
    const requestUrl = new URL(url, window.location.origin);
    if (effectiveQuery) {
      requestUrl.searchParams.set('q', effectiveQuery);
    }
    return fetch(requestUrl.toString(), {
      headers: {
        'X-Requested-With': 'XMLHttpRequest',
      },
      signal: state.abortController.signal,
    })
      .then((response) => {
        if (!response.ok) {
          throw new Error(`Global search failed: ${response.status}`);
        }
        return response.text();
      })
      .then((html) => {
        if (requestToken !== state.requestToken) {
          return;
        }
        state.panel.innerHTML = html;
        state.loadedQuery = query;
        state.isLoading = false;
        openGlobalSearch(state);
        syncGlobalSearchActiveResult(state, 0);
      })
      .catch((error) => {
        if (requestToken === state.requestToken) {
          state.isLoading = false;
        }
        if (error.name !== 'AbortError') {
          window.console.error(error);
        }
      });
  }

  function scheduleGlobalSearch(state, rawQuery) {
    if (state.timer) {
      window.clearTimeout(state.timer);
    }
    state.timer = window.setTimeout(() => {
      requestGlobalSearch(state, rawQuery);
    }, GLOBAL_SEARCH_DEBOUNCE_MS);
  }

  async function submitGlobalSearch(state) {
    const query = state.input.value.trim();
    if (!query) {
      closeGlobalSearch(state);
      return;
    }
    const hasFreshResults = state.loadedQuery === query && getSearchResultLinks(state).length;
    if (!hasFreshResults) {
      await requestGlobalSearch(state, query);
    }
    if (!isRunnableSearchQuery(query)) {
      openGlobalSearch(state);
      return;
    }
    const links = getSearchResultLinks(state);
    const target = links[state.activeIndex] || links[0];
    if (target) {
      window.location.href = target.href;
      return;
    }
    state.form.submit();
  }

  function wireGlobalSearch(root) {
    root.querySelectorAll('[data-manager-global-search-root]').forEach((searchRoot) => {
      const form = searchRoot.querySelector('[data-manager-global-search]');
      if (!form || form.dataset.managerBound === '1') {
        return;
      }
      const input = form.querySelector('[data-manager-global-search-input]');
      const panel = searchRoot.querySelector('[data-manager-global-search-panel]');
      const backdrop = searchRoot.hasAttribute('data-overlay-search-root')
        ? null
        : document.querySelector('[data-manager-global-search-backdrop]');
      if (!input || !panel) {
        return;
      }
      form.dataset.managerBound = '1';
      const state = {
        root: searchRoot,
        form,
        input,
        panel,
        backdrop,
        timer: null,
        abortController: null,
        activeIndex: -1,
        lastQuery: '',
        loadedQuery: '',
        isLoading: false,
        requestToken: 0,
      };
      globalSearchStates.push(state);

      syncResponsivePlaceholder(input);

      input.addEventListener('focus', () => {
        globalSearchState = state;
        requestGlobalSearch(state, input.value.trim());
      });

      input.addEventListener('input', () => {
        globalSearchState = state;
        scheduleGlobalSearch(state, input.value.trim());
      });

      input.addEventListener('keydown', (event) => {
        globalSearchState = state;
        const links = getSearchResultLinks(state);
        if (event.key === 'ArrowDown' && links.length) {
          event.preventDefault();
          syncGlobalSearchActiveResult(state, state.activeIndex + 1);
          return;
        }
        if (event.key === 'ArrowUp' && links.length) {
          event.preventDefault();
          syncGlobalSearchActiveResult(state, state.activeIndex - 1);
          return;
        }
        if (event.key === 'Enter') {
          event.preventDefault();
          submitGlobalSearch(state);
          return;
        }
        if (event.key === 'Escape') {
          event.preventDefault();
          closeGlobalSearch(state);
          input.blur();
          closeGlobalSearchOverlay();
        }
      });

      form.addEventListener('submit', (event) => {
        event.preventDefault();
        globalSearchState = state;
        submitGlobalSearch(state);
      });

      window.addEventListener('resize', () => syncResponsivePlaceholder(input));
    });
  }

  function wireGlobalSearchOverlay(root) {
    root.querySelectorAll('[data-global-search-open]').forEach((button) => {
      if (button.dataset.managerBound === '1') {
        return;
      }
      button.dataset.managerBound = '1';
      button.addEventListener('click', () => {
        openGlobalSearchOverlay();
      });
    });

    root.querySelectorAll('[data-global-search-close]').forEach((button) => {
      if (button.dataset.managerBound === '1') {
        return;
      }
      button.dataset.managerBound = '1';
      button.addEventListener('click', () => {
        closeGlobalSearchOverlay();
      });
    });
  }

  function debounceSubmit(form) {
    const existing = filterTimers.get(form);
    if (existing) {
      window.clearTimeout(existing);
    }
    const timer = window.setTimeout(() => {
      form.requestSubmit();
    }, FILTER_DEBOUNCE_MS);
    filterTimers.set(form, timer);
  }

  function normalizeSearchText(value) {
    return String(value || '')
      .toLowerCase()
      .replace(/ё/g, 'е')
      .replace(/\s+/g, ' ')
      .trim();
  }

  function parseManagerDate(value) {
    if (!window.flatpickr) {
      return null;
    }
    const normalized = String(value || '').trim();
    if (!normalized) {
      return null;
    }
    if (/^\d{4}-\d{2}-\d{2}$/.test(normalized)) {
      return window.flatpickr.parseDate(normalized, 'Y-m-d');
    }
    if (/^\d{2}\.\d{2}\.\d{4}$/.test(normalized)) {
      return window.flatpickr.parseDate(normalized, 'd.m.Y');
    }
    return null;
  }

  function digitsOnly(value) {
    return String(value || '').replace(/\D+/g, '');
  }

  function formatPhoneMask(value) {
    let digits = digitsOnly(value);
    if (!digits) {
      return '';
    }
    if (digits.length === 11 && digits.startsWith('8')) {
      digits = `7${digits.slice(1)}`;
    } else if (digits.length === 10) {
      digits = `7${digits}`;
    }
    if (!digits.startsWith('7')) {
      return `+${digits.slice(0, 15)}`;
    }
    const local = digits.slice(1, 11);
    const code = local.slice(0, 3);
    const first = local.slice(3, 6);
    const second = local.slice(6, 8);
    const third = local.slice(8, 10);
    let formatted = '+7';
    if (code) {
      formatted += ` (${code}`;
      if (code.length === 3) {
        formatted += ')';
      }
    }
    if (first) {
      formatted += ` ${first}`;
    }
    if (second) {
      formatted += `-${second}`;
    }
    if (third) {
      formatted += `-${third}`;
    }
    return formatted;
  }

  function formatDateMask(value) {
    const digits = digitsOnly(value).slice(0, 8);
    if (!digits) {
      return '';
    }
    if (digits.length <= 2) {
      return digits;
    }
    if (digits.length <= 4) {
      return `${digits.slice(0, 2)}.${digits.slice(2)}`;
    }
    return `${digits.slice(0, 2)}.${digits.slice(2, 4)}.${digits.slice(4)}`;
  }

  function normalizeTelegramValue(value) {
    const trimmed = String(value || '').trim();
    if (!trimmed) {
      return '';
    }
    const normalized = trimmed
      .replace(/^https?:\/\/t\.me\//i, '')
      .replace(/^t\.me\//i, '')
      .trim();
    if (!normalized || /\s/.test(normalized)) {
      return trimmed;
    }
    return normalized.startsWith('@') ? normalized : `@${normalized}`;
  }

  function wireFieldMasks(root) {
    root.querySelectorAll('[data-manager-mask]').forEach((input) => {
      const maskKind = input.dataset.managerMask;
      if (!maskKind) {
        return;
      }
      if (input.dataset.managerMaskBound === '1') {
        return;
      }
      input.dataset.managerMaskBound = '1';

      if (maskKind === 'phone') {
        const syncPhone = () => {
          input.value = formatPhoneMask(input.value);
        };
        input.addEventListener('input', syncPhone);
        input.addEventListener('blur', syncPhone);
        return;
      }

      if (maskKind === 'email') {
        input.addEventListener('blur', () => {
          input.value = String(input.value || '').trim().toLowerCase();
        });
        return;
      }

      if (maskKind === 'telegram' || maskKind === 'telegram-loose') {
        input.addEventListener('blur', () => {
          input.value = normalizeTelegramValue(input.value);
        });
        return;
      }

      if (maskKind === 'date') {
        const syncDate = () => {
          input.value = formatDateMask(input.value);
        };
        input.addEventListener('input', syncDate);
        input.addEventListener('blur', () => {
          syncDate();
          const datePickerHostId = input.dataset.managerDateSourceId;
          if (!datePickerHostId) {
            return;
          }
          const hiddenInput = document.getElementById(datePickerHostId);
          if (!hiddenInput || !hiddenInput._flatpickr) {
            return;
          }
          const parsedDate = parseManagerDate(input.value);
          if (!parsedDate) {
            return;
          }
          hiddenInput._flatpickr.setDate(parsedDate, true);
        });
      }
    });
  }

  function wireDatePickers(root) {
    if (!window.flatpickr) {
      return;
    }
    root.querySelectorAll('[data-manager-date-picker]').forEach((input) => {
      if (input.dataset.managerDatePickerBound === '1' || input._flatpickr) {
        return;
      }
      input.dataset.managerDatePickerBound = '1';
      const inputClassName = input.className;
      const inputPlaceholder = input.getAttribute('placeholder') || 'ДД.ММ.ГГГГ';
      window.flatpickr(input, {
        altInput: true,
        altFormat: 'd.m.Y',
        dateFormat: 'Y-m-d',
        disableMobile: true,
        allowInput: true,
        locale: window.flatpickr.l10ns && window.flatpickr.l10ns.ru ? window.flatpickr.l10ns.ru : 'default',
        parseDate: parseManagerDate,
        prevArrow: '‹',
        nextArrow: '›',
        onReady: (_selectedDates, _dateStr, instance) => {
          instance.calendarContainer.classList.add('manager-flatpickr-calendar');
          if (instance.altInput) {
            instance.altInput.className = inputClassName;
            instance.altInput.placeholder = inputPlaceholder;
            instance.altInput.dataset.managerMask = 'date';
            if (instance.input.id) {
              instance.altInput.dataset.managerDateSourceId = instance.input.id;
            }
          }
          if (instance.selectedDates.length) {
            instance.input.value = instance.formatDate(instance.selectedDates[0], 'Y-m-d');
          }
        },
        onChange: (_selectedDates, _dateStr, instance) => {
          instance.input.dispatchEvent(new Event('input', {bubbles: true}));
          instance.input.dispatchEvent(new Event('change', {bubbles: true}));
        },
      });
    });
  }

  function wireDatePickerTriggers(root) {
    root.querySelectorAll('[data-manager-date-picker-trigger]').forEach((button) => {
      if (button.dataset.managerBound === '1') {
        return;
      }
      button.dataset.managerBound = '1';
      button.addEventListener('click', () => {
        const shell = button.closest('.manager-date-picker-shell');
        const input = shell ? shell.querySelector('[data-manager-date-picker]') : null;
        if (input && input._flatpickr) {
          input._flatpickr.open();
          if (input._flatpickr.altInput) {
            input._flatpickr.altInput.focus();
          }
          return;
        }
        const fallbackInput = shell ? shell.querySelector('.manager-date-picker-input') : null;
        if (fallbackInput) {
          fallbackInput.focus();
          if (typeof fallbackInput.showPicker === 'function') {
            fallbackInput.showPicker();
          }
        }
      });
    });
  }

  function wireBulkSelection(root) {
    const bulkToolbar = root.querySelector('#bulk-toolbar');
    const selectAll = root.querySelector('#bulk-select-all');
    const clearButton = root.querySelector('#bulk-clear-selection');
    const checkboxes = Array.from(root.querySelectorAll('.bulk-deal-checkbox'));
    const countTarget = root.querySelector('#bulk-selected-count');
    const hiddenInputs = Array.from(root.querySelectorAll('.bulk-deal-ids-input'));
    if (!bulkToolbar || !checkboxes.length || !countTarget || !hiddenInputs.length) {
      return;
    }

    const syncSelectionState = () => {
      const selected = checkboxes.filter((checkbox) => checkbox.checked).map((checkbox) => checkbox.value);
      countTarget.textContent = String(selected.length);
      hiddenInputs.forEach((input) => {
        input.value = selected.join(',');
      });
      bulkToolbar.hidden = selected.length === 0;
      if (selectAll) {
        selectAll.checked = selected.length > 0 && selected.length === checkboxes.length;
        selectAll.indeterminate = selected.length > 0 && selected.length < checkboxes.length;
      }
    };

    if (selectAll && selectAll.dataset.managerBound !== '1') {
      selectAll.dataset.managerBound = '1';
      selectAll.addEventListener('change', () => {
        checkboxes.forEach((checkbox) => {
          checkbox.checked = selectAll.checked;
        });
        syncSelectionState();
      });
    }

    if (clearButton && clearButton.dataset.managerBound !== '1') {
      clearButton.dataset.managerBound = '1';
      clearButton.addEventListener('click', () => {
        checkboxes.forEach((checkbox) => {
          checkbox.checked = false;
        });
        syncSelectionState();
      });
    }

    checkboxes.forEach((checkbox) => {
      if (checkbox.dataset.managerBound === '1') {
        return;
      }
      checkbox.dataset.managerBound = '1';
      checkbox.addEventListener('change', syncSelectionState);
    });

    syncSelectionState();
  }

  function wireScrollFade(root) {
    root.querySelectorAll('[data-scroll-fade]').forEach((container) => {
      const viewport = container.querySelector('[data-scroll-fade-viewport]') || container;
      if (!viewport) {
        return;
      }

      const updateFadeState = () => {
        const maxScrollLeft = Math.max(viewport.scrollWidth - viewport.clientWidth, 0);
        container.toggleAttribute('data-scrollable', maxScrollLeft > 6);
        container.toggleAttribute('data-scroll-left', viewport.scrollLeft > 4);
        container.toggleAttribute('data-scroll-right', viewport.scrollLeft < maxScrollLeft - 4);
      };

      if (viewport.dataset.scrollFadeBound !== '1') {
        viewport.dataset.scrollFadeBound = '1';
        viewport.addEventListener('scroll', updateFadeState, {passive: true});
        window.addEventListener('resize', updateFadeState);
      }

      window.requestAnimationFrame(updateFadeState);
    });
  }

  function wireFilterSearch(root) {
    root.querySelectorAll('[data-filter-search-root]').forEach((searchRoot) => {
      const input = searchRoot.querySelector('[data-filter-search-input]');
      if (!input || input.dataset.managerBound === '1') {
        return;
      }

      const clearButton = searchRoot.querySelector('[data-filter-search-clear]');
      const statusNode = searchRoot.querySelector('[data-filter-search-status]');
      const emptyState = searchRoot.querySelector('[data-filter-search-empty]');
      const sections = Array.from(searchRoot.querySelectorAll('[data-filter-search-section]')).map((section) => ({
        section,
        title: normalizeSearchText(section.querySelector('[data-filter-search-section-title]')?.textContent || ''),
        items: Array.from(section.querySelectorAll('[data-filter-search-item]')).map((item) => ({
          element: item,
          text: normalizeSearchText(item.dataset.filterSearchItem || item.textContent),
        })),
      }));

      const updateSearch = () => {
        const query = normalizeSearchText(input.value);
        let visibleItems = 0;

        sections.forEach(({section, title, items}) => {
          const sectionMatches = Boolean(query) && title.includes(query);
          let visibleInSection = 0;

          items.forEach((item) => {
            const matches = !query || sectionMatches || item.text.includes(query);
            item.element.hidden = !matches;
            if (matches) {
              visibleItems += 1;
              visibleInSection += 1;
            }
          });

          section.hidden = Boolean(query) && visibleInSection === 0;
        });

        if (clearButton) {
          clearButton.hidden = !query;
        }
        if (emptyState) {
          emptyState.hidden = !query || visibleItems > 0;
        }
        if (statusNode) {
          if (!query) {
            statusNode.textContent = 'Показываем все фильтры.';
          } else if (visibleItems > 0) {
            statusNode.textContent = `Найдено фильтров: ${visibleItems}.`;
          } else {
            statusNode.textContent = 'Совпадений не найдено.';
          }
        }
      };

      input.dataset.managerBound = '1';
      input.addEventListener('input', updateSearch);

      if (clearButton && clearButton.dataset.managerBound !== '1') {
        clearButton.dataset.managerBound = '1';
        clearButton.addEventListener('click', () => {
          input.value = '';
          updateSearch();
          input.focus();
        });
      }

      updateSearch();
    });
  }

  function wireAutoFilters(root) {
    root.querySelectorAll('[data-manager-filter-form]').forEach((form) => {
      form.querySelectorAll('input, select, textarea').forEach((field) => {
        const eventName = field.type === 'checkbox' || field.type === 'radio' || field.tagName === 'SELECT'
          ? 'change'
          : 'input';
        if (field.dataset.managerBound === '1') {
          return;
        }
        field.dataset.managerBound = '1';
        field.addEventListener(eventName, () => debounceSubmit(form));
      });
    });
  }

  function parseFilterAssignments(rawValue) {
    return String(rawValue || '')
      .split(',')
      .map((entry) => entry.trim())
      .filter(Boolean)
      .map((entry) => {
        const [id, ...valueParts] = entry.split('=');
        return {
          id: (id || '').trim(),
          value: valueParts.join('=').trim(),
        };
      })
      .filter((item) => item.id);
  }

  function applyFilterAssignments(assignments, nextValue = '') {
    assignments.forEach(({id}) => {
      const input = document.getElementById(id);
      if (input) {
        input.value = nextValue;
      }
    });
  }

  function matchFilterAssignments(assignments) {
    return assignments.length > 0 && assignments.every(({id, value}) => {
      const input = document.getElementById(id);
      return input && String(input.value || '') === value;
    });
  }

  function syncDealFilterToggleState(root) {
    root.querySelectorAll('[data-filter-toggle-button]').forEach((button) => {
      const isActive = matchFilterAssignments(parseFilterAssignments(button.dataset.filterActiveCheck));
      button.classList.toggle('is-active', isActive);
      button.setAttribute('aria-pressed', isActive ? 'true' : 'false');
    });
  }

  function wireDealFilterToggles(root) {
    root.querySelectorAll('[data-filter-toggle-button]').forEach((button) => {
      if (button.dataset.managerBound === '1') {
        return;
      }
      button.dataset.managerBound = '1';
      button.addEventListener('click', () => {
        const activeAssignments = parseFilterAssignments(button.dataset.filterActiveCheck);
        const isActive = matchFilterAssignments(activeAssignments);
        applyFilterAssignments(parseFilterAssignments(button.dataset.filterClear), '');
        if (!isActive) {
          parseFilterAssignments(button.dataset.filterSet).forEach(({id, value}) => {
            const input = document.getElementById(id);
            if (input) {
              input.value = value;
            }
          });
        }
        syncDealFilterToggleState(document);
      });
    });
    syncDealFilterToggleState(root);
  }

  function wireDisclosureToggles(root) {
    root.querySelectorAll('[data-manager-disclosure-button]').forEach((button) => {
      if (button.dataset.managerBound === '1') {
        return;
      }
      const targetSelector = button.dataset.managerDisclosureTarget;
      const target = targetSelector ? document.querySelector(targetSelector) : null;
      if (!target) {
        return;
      }
      button.dataset.managerBound = '1';
      const syncDisclosureState = (isExpanded) => {
        button.setAttribute('aria-expanded', isExpanded ? 'true' : 'false');
        const icon = button.querySelector('[data-manager-disclosure-icon]');
        if (icon) {
          icon.textContent = isExpanded ? '▾' : '▸';
        }
      };
      syncDisclosureState(!target.hasAttribute('hidden'));
      button.addEventListener('click', () => {
        const shouldExpand = target.hasAttribute('hidden');
        if (shouldExpand) {
          target.removeAttribute('hidden');
        } else {
          target.setAttribute('hidden', 'hidden');
        }
        syncDisclosureState(shouldExpand);
      });
    });
  }

  function wireDrawers(root) {
    function openDrawer(drawerSelector) {
      const target = document.querySelector(drawerSelector);
      const overlay = document.querySelector('[data-drawer-overlay]');
      if (target) {
        target.classList.add('is-open');
        target.setAttribute('aria-hidden', 'false');
      }
      if (overlay) {
        overlay.classList.add('is-open');
      }
      document.documentElement.style.overflow = 'hidden';
    }

    root.querySelectorAll('[data-drawer-target]').forEach((button) => {
      if (button.dataset.managerBound === '1') {
        return;
      }
      button.dataset.managerBound = '1';
      button.addEventListener('click', () => {
        if (button.dataset.drawerTarget === '#manager-remote-drawer') {
          const remoteContent = document.querySelector('#manager-remote-drawer-content');
          if (remoteContent) {
            remoteContent.innerHTML = `
              <div class="flex items-start justify-between gap-4">
                <div>
                  <p class="text-xs uppercase tracking-[0.2em] text-slate-500">Loading</p>
                  <h2 class="mt-2 text-2xl font-semibold text-white">Загружаем сценарий</h2>
                  <p class="mt-2 text-sm text-slate-400">Подтягиваем форму или связанную сущность сделки в drawer.</p>
                </div>
                <button type="button" data-drawer-close class="rounded-full border border-slate-700 px-3 py-1 text-sm">Закрыть</button>
              </div>
            `;
          }
        }
        openDrawer(button.dataset.drawerTarget);
      });
    });

    root.querySelectorAll('[data-open-drawer-on-load]').forEach((marker) => {
      if (marker.dataset.managerBound === '1') {
        return;
      }
      marker.dataset.managerBound = '1';
      openDrawer(marker.dataset.openDrawerOnLoad);
    });

    root.querySelectorAll('[data-drawer-close]').forEach((button) => {
      if (button.dataset.managerBound === '1') {
        return;
      }
      button.dataset.managerBound = '1';
      button.addEventListener('click', () => closeDrawers());
    });
  }

  function wireRemoteDrawer(root) {
    const remoteDrawerContent = root.querySelector('#manager-remote-drawer-content');
    if (!remoteDrawerContent) {
      return;
    }
    const currentUrl = remoteDrawerContent.dataset.currentUrl || '';
    remoteDrawerContent.querySelectorAll('form').forEach((form) => {
      if (!form.getAttribute('action') && currentUrl) {
        form.setAttribute('action', currentUrl);
      }
    });
    const manualOrderForm = remoteDrawerContent.querySelector('form[data-manual-order-form]');
    if (!manualOrderForm || manualOrderForm.dataset.managerDrawerBound === '1') {
      return;
    }
    manualOrderForm.dataset.managerDrawerBound = '1';
    if (currentUrl) {
      manualOrderForm.setAttribute('action', currentUrl);
      manualOrderForm.setAttribute('hx-post', currentUrl);
    }
    manualOrderForm.setAttribute('hx-select', '#manager-main-content > *');
    manualOrderForm.setAttribute('hx-target', '#manager-remote-drawer-content');
    manualOrderForm.setAttribute('hx-swap', 'innerHTML');
    manualOrderForm.setAttribute('hx-push-url', 'false');
    if (window.htmx) {
      window.htmx.process(manualOrderForm);
    }
  }

  function closeDrawers() {
    document.querySelectorAll('.manager-drawer, .manager-mobile-sidebar').forEach((panel) => {
      panel.classList.remove('is-open');
      panel.setAttribute('aria-hidden', 'true');
    });
    const overlay = document.querySelector('[data-drawer-overlay]');
    if (overlay) {
      overlay.classList.remove('is-open');
    }
    document.documentElement.style.overflow = '';
  }

  function wireMessages(root) {
    root.querySelectorAll('[data-manager-flash]').forEach((message) => {
      if (message.dataset.managerBound === '1') {
        return;
      }
      message.dataset.managerBound = '1';
      window.setTimeout(() => {
        message.style.opacity = '0';
        message.style.transform = 'translateY(-4px)';
        window.setTimeout(() => message.remove(), 200);
      }, 4200);
    });
  }

  function wireMobileSidebar(root) {
    root.querySelectorAll('[data-mobile-sidebar-open]').forEach((button) => {
      if (button.dataset.managerBound === '1') {
        return;
      }
      button.dataset.managerBound = '1';
      button.addEventListener('click', () => {
        const sidebar = document.querySelector('.manager-mobile-sidebar');
        const overlay = document.querySelector('[data-drawer-overlay]');
        if (sidebar) {
          sidebar.classList.add('is-open');
          sidebar.setAttribute('aria-hidden', 'false');
        }
        if (overlay) {
          overlay.classList.add('is-open');
        }
        document.documentElement.style.overflow = 'hidden';
      });
    });
  }

  function wireCopyActions(root) {
    root.querySelectorAll('[data-copy-text]').forEach((button) => {
      if (button.dataset.managerBound === '1') {
        return;
      }
      button.dataset.managerBound = '1';
      const initialLabel = button.textContent;
      const successLabel = button.dataset.copySuccessLabel || 'Скопировано';
      button.addEventListener('click', async (event) => {
        event.preventDefault();
        const copyText = button.dataset.copyText || '';
        if (!copyText) {
          return;
        }
        try {
          if (navigator.clipboard && navigator.clipboard.writeText) {
            await navigator.clipboard.writeText(copyText);
          } else {
            window.prompt('Скопируйте значение', copyText);
            return;
          }
          button.textContent = successLabel;
          window.setTimeout(() => {
            button.textContent = initialLabel;
          }, 1400);
        } catch (error) {
          window.prompt('Скопируйте значение', copyText);
        }
      });
    });
  }

  function parseMoney(value) {
    const normalized = String(value || '').replace(/\s+/g, '').replace(',', '.').trim();
    const parsed = window.parseFloat(normalized);
    return Number.isFinite(parsed) ? parsed : 0;
  }

  function formatMoney(value) {
    const numeric = Number(value);
    const safe = Number.isFinite(numeric) ? Math.round((numeric + Number.EPSILON) * 100) / 100 : 0;
    const isInteger = Math.abs(safe % 1) < 0.000001;
    const formatted = new Intl.NumberFormat('ru-RU', {
      minimumFractionDigits: isInteger ? 0 : 2,
      maximumFractionDigits: 2,
    }).format(safe).replace(/[\u00A0\u202F]/g, ' ');
    return `${formatted} ₽`;
  }

  function loadChartJs() {
    if (window.Chart) {
      return Promise.resolve(window.Chart);
    }
    if (chartJsPromise) {
      return chartJsPromise;
    }
    chartJsPromise = new Promise((resolve, reject) => {
      const existing = document.querySelector('script[data-manager-chartjs="1"]');
      if (existing) {
        existing.addEventListener('load', () => resolve(window.Chart), {once: true});
        existing.addEventListener('error', reject, {once: true});
        return;
      }
      const script = document.createElement('script');
      script.src = CHART_JS_URL;
      script.async = true;
      script.dataset.managerChartjs = '1';
      script.addEventListener('load', () => resolve(window.Chart), {once: true});
      script.addEventListener('error', (event) => {
        chartJsPromise = null;
        reject(event);
      }, {once: true});
      document.head.appendChild(script);
    });
    return chartJsPromise;
  }

  function wireFinanceCashflowChart(root) {
    const canvas = root.matches?.('[data-finance-cashflow-chart]')
      ? root
      : root.querySelector('[data-finance-cashflow-chart]');
    if (!canvas || canvas.dataset.managerChartBound === '1') {
      return;
    }
    const dataNodeId = canvas.dataset.financeCashflowSource;
    const dataNode = dataNodeId ? document.getElementById(dataNodeId) : null;
    if (!dataNode) {
      return;
    }

    let payload = null;
    try {
      payload = JSON.parse(dataNode.textContent || '{}');
    } catch (error) {
      window.console.error('Cashflow payload parse failed', error);
      return;
    }

    canvas.dataset.managerChartBound = '1';
    loadChartJs()
      .then(() => {
        if (!canvas.isConnected) {
          return;
        }
        const context = canvas.getContext('2d');
        if (!context) {
          return;
        }
        if (canvas._managerChart) {
          canvas._managerChart.destroy();
        }

        const labels = Array.isArray(payload.labels) ? payload.labels : [];
        const income = Array.isArray(payload.income) ? payload.income.map((value) => parseMoney(value)) : [];
        const operatingExpense = Array.isArray(payload.operating_expense)
          ? payload.operating_expense.map((value) => -Math.abs(parseMoney(value)))
          : [];
        const payout = Array.isArray(payload.payout)
          ? payload.payout.map((value) => -Math.abs(parseMoney(value)))
          : [];
        const balance = Array.isArray(payload.balance) ? payload.balance.map((value) => parseMoney(value)) : [];

        canvas._managerChart = new window.Chart(context, {
          data: {
            labels,
            datasets: [
              {
                type: 'bar',
                label: 'Входящий поток',
                data: income,
                backgroundColor: 'rgba(16, 185, 129, 0.72)',
                borderRadius: 10,
                maxBarThickness: 20,
              },
              {
                type: 'bar',
                label: 'Наши расходы',
                data: operatingExpense,
                backgroundColor: 'rgba(245, 158, 11, 0.70)',
                borderRadius: 10,
                maxBarThickness: 20,
              },
              {
                type: 'bar',
                label: 'Выплаты партнерам',
                data: payout,
                backgroundColor: 'rgba(244, 63, 94, 0.70)',
                borderRadius: 10,
                maxBarThickness: 20,
              },
              {
                type: 'line',
                label: 'Баланс',
                data: balance,
                borderColor: 'rgb(34, 211, 238)',
                backgroundColor: 'rgba(34, 211, 238, 0.12)',
                borderWidth: 2,
                pointRadius: 0,
                pointHoverRadius: 4,
                pointHoverBackgroundColor: 'rgb(34, 211, 238)',
                tension: 0.35,
              },
            ],
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: {
              mode: 'index',
              intersect: false,
            },
            plugins: {
              legend: {
                labels: {
                  color: '#cbd5e1',
                  usePointStyle: true,
                  pointStyle: 'circle',
                  boxWidth: 10,
                },
              },
              tooltip: {
                callbacks: {
                  label(context) {
                    const rawValue = Number(context.raw || 0);
                    const displayValue = context.dataset.type === 'bar' ? Math.abs(rawValue) : rawValue;
                    return `${context.dataset.label}: ${formatMoney(displayValue)}`;
                  },
                },
              },
            },
            scales: {
              x: {
                grid: {
                  display: false,
                },
                ticks: {
                  color: '#94a3b8',
                  autoSkip: true,
                  maxRotation: 0,
                  maxTicksLimit: 10,
                },
              },
              y: {
                grid: {
                  color: 'rgba(51, 65, 85, 0.45)',
                },
                ticks: {
                  color: '#94a3b8',
                  callback(value) {
                    return formatMoney(value);
                  },
                },
              },
            },
          },
        });
      })
      .catch((error) => {
        window.console.error('Chart.js failed to load', error);
      });
  }

  const DEAL_STATUS_OPTIONS = {
    sale_on_request: [
      ['new_request', 'Новая заявка'],
      ['awaiting_prepayment', 'Ожидает предоплату'],
      ['prepayment_received', 'Предоплата получена'],
      ['supplier_ordered', 'Заказ размещен у поставщика'],
      ['in_transit', 'Товар в пути'],
      ['received', 'Товар поступил'],
      ['ready_to_ship', 'Готов к отправке'],
      ['shipped', 'Отправлен'],
      ['completed', 'Завершена'],
      ['cancelled', 'Отменена'],
    ],
    sale_from_stock: [
      ['new', 'Новая'],
      ['reserved', 'Резерв создан'],
      ['awaiting_payment', 'Ожидает оплату'],
      ['paid', 'Оплачена'],
      ['assembling', 'Собирается'],
      ['shipped', 'Отправлена'],
      ['completed', 'Завершена'],
      ['cancelled', 'Отменена'],
    ],
    trade_in: [
      ['new_request', 'Новая заявка'],
      ['awaiting_evaluation', 'Ожидает оценку'],
      ['evaluated', 'Оценено'],
      ['terms_agreed', 'Условия согласованы'],
      ['awaiting_device_shipment', 'Ожидает отправку устройства клиентом'],
      ['device_received', 'Устройство получено'],
      ['inspected', 'Проверено'],
      ['ready_for_exchange', 'Готово к обмену'],
      ['topup_received', 'Доплата получена'],
      ['new_item_shipped', 'Новый товар отправлен'],
      ['completed', 'Завершена'],
      ['cancelled', 'Отменена'],
    ],
    avito_sale: [
      ['new', 'Новая'],
      ['shipped', 'Отправлено'],
      ['received_by_customer', 'Чел забрал'],
      ['returned', 'Возврат'],
    ],
  };

  function isAvitoWorkflow(form) {
    const dealType = form.querySelector('[name="deal_type"]')?.value;
    const customerSource = form.querySelector('[name="customer_source"]')?.value;
    return dealType === 'avito_sale' || customerSource === 'avito';
  }

  function renumberItemRows(form) {
    const visibleRows = Array.from(form.querySelectorAll('[data-order-item-row]')).filter((row) => !row.hidden);
    visibleRows.forEach((row, index) => {
      const label = row.querySelector('.text-sm.font-medium.text-slate-200');
      if (label) {
        label.textContent = `Позиция ${index + 1}`;
      }
    });
  }

  function renumberTradeInRows(form) {
    const visibleRows = Array.from(form.querySelectorAll('[data-tradein-item-row]')).filter((row) => !row.hidden);
    visibleRows.forEach((row, index) => {
      const label = row.querySelector('.text-sm.font-medium.text-slate-200');
      if (label) {
        label.textContent = `Принимаемая позиция ${index + 1}`;
      }
    });
  }

  function updateDealStatusOptions(form) {
    const dealType = form.querySelector('[name="deal_type"]')?.value;
    const statusField = form.querySelector('[name="deal_status"]');
    if (!dealType || !statusField) {
      return;
    }
    const allowed = isAvitoWorkflow(form)
      ? DEAL_STATUS_OPTIONS.avito_sale
      : (DEAL_STATUS_OPTIONS[dealType] || []);
    const current = statusField.value;
    statusField.innerHTML = '';
    allowed.forEach(([value, label], index) => {
      const option = document.createElement('option');
      option.value = value;
      option.textContent = label;
      if (value === current || (!current && index === 0)) {
        option.selected = true;
      }
      statusField.appendChild(option);
    });
    if (!allowed.some(([value]) => value === statusField.value) && allowed[0]) {
      statusField.value = allowed[0][0];
    }
  }

  function syncManualOrderDisabledState(form) {
    form.querySelectorAll('input, select, textarea').forEach((field) => {
      if (field.type === 'hidden') {
        return;
      }
      field.disabled = Boolean(field.closest('[hidden]'));
    });
  }

  function updateManualOrderVisibility(form) {
    const dealType = form.querySelector('[name="deal_type"]')?.value;
    const buyerType = form.querySelector('[name="buyer_type"]')?.value;
    const deliveryMethod = form.querySelector('[name="delivery_method"]')?.value;
    const avitoWorkflow = isAvitoWorkflow(form);

    form.querySelectorAll('[data-buyer-section]').forEach((section) => {
      section.hidden = section.dataset.buyerSection !== buyerType;
    });
    form.querySelectorAll('[data-deal-section]').forEach((section) => {
      if (section.dataset.dealSection === 'avito_sale') {
        section.hidden = !avitoWorkflow;
        return;
      }
      section.hidden = section.dataset.dealSection !== dealType;
    });
    form.querySelectorAll('[data-avito-hide]').forEach((section) => {
      section.hidden = avitoWorkflow;
    });
    form.querySelectorAll('[data-delivery-group]').forEach((section) => {
      if (section.dataset.deliveryGroup === 'pickup') {
        section.hidden = deliveryMethod !== 'cdek_pvz';
      } else if (section.dataset.deliveryGroup === 'address') {
        section.hidden = !['cdek_courier', 'city_delivery', 'other_transport'].includes(deliveryMethod);
      }
    });
    syncManualOrderDisabledState(form);
  }

  let manualOrderProductCatalog = null;

  function normalizeManualOrderProductName(value) {
    return String(value || '').trim().replace(/\s+/g, ' ').toLowerCase();
  }

  function getManualOrderProductCatalog() {
    if (manualOrderProductCatalog) {
      return manualOrderProductCatalog;
    }
    const node = document.getElementById('manual-order-product-catalog');
    const catalog = {byName: new Map()};
    if (!node) {
      manualOrderProductCatalog = catalog;
      return catalog;
    }
    try {
      const items = JSON.parse(node.textContent || '[]');
      items.forEach((item) => {
        const key = normalizeManualOrderProductName(item.name);
        if (key) {
          catalog.byName.set(key, item);
        }
      });
    } catch (error) {
      window.console.warn('Unable to parse manual order product catalog.', error);
    }
    manualOrderProductCatalog = catalog;
    return catalog;
  }

  function syncManualOrderProductRow(row) {
    const nameInput = row.querySelector('[name$="-product_name"]');
    const productInput = row.querySelector('[name$="-product"]');
    const salePriceInput = row.querySelector('[name$="-sale_price"]');
    const preview = row.querySelector('[data-order-product-preview]');
    if (!nameInput || !productInput || !preview) {
      return;
    }
    const imageNode = preview.querySelector('[data-order-product-preview-image]');
    const titleNode = preview.querySelector('[data-order-product-preview-title]');
    const statusNode = preview.querySelector('[data-order-product-preview-status]');
    const priceNode = preview.querySelector('[data-order-product-preview-price]');
    const normalizedName = normalizeManualOrderProductName(nameInput.value);
    const matchedProduct = normalizedName ? getManualOrderProductCatalog().byName.get(normalizedName) : null;

    if (!normalizedName) {
      productInput.value = '';
      preview.classList.add('hidden');
      if (imageNode) {
        imageNode.classList.add('hidden');
        imageNode.removeAttribute('src');
      }
      if (priceNode) {
        priceNode.textContent = '';
      }
      return;
    }

    preview.classList.remove('hidden');
    if (matchedProduct) {
      const previousProductId = productInput.value;
      productInput.value = String(matchedProduct.id);
      if (
        salePriceInput
        && (!salePriceInput.value || salePriceInput.dataset.catalogAutofilled === '1' || previousProductId !== String(matchedProduct.id))
      ) {
        salePriceInput.value = matchedProduct.price;
        salePriceInput.dataset.catalogAutofilled = '1';
      }
      if (titleNode) {
        titleNode.textContent = matchedProduct.name;
      }
      if (statusNode) {
        statusNode.textContent = 'Товар найден в каталоге. Цена подставлена автоматически, её можно скорректировать.';
      }
      if (priceNode) {
        priceNode.textContent = formatMoney(parseMoney(matchedProduct.price));
      }
      if (imageNode) {
        if (matchedProduct.image_url) {
          imageNode.src = matchedProduct.image_url;
          imageNode.alt = matchedProduct.name;
          imageNode.classList.remove('hidden');
        } else {
          imageNode.classList.add('hidden');
          imageNode.removeAttribute('src');
        }
      }
      return;
    }

    productInput.value = '';
    if (titleNode) {
      titleNode.textContent = nameInput.value.trim();
    }
    if (statusNode) {
      statusNode.textContent = 'Позиция не найдена в каталоге. Укажите полное наименование и цену вручную.';
    }
    if (priceNode) {
      priceNode.textContent = '';
    }
    if (imageNode) {
      imageNode.classList.add('hidden');
      imageNode.removeAttribute('src');
    }
  }

  function syncManualOrderProductRows(form) {
    form.querySelectorAll('[data-order-item-row]').forEach((row) => {
      if (!row.hidden) {
        syncManualOrderProductRow(row);
      }
    });
  }

  function updateManualOrderSummary(form) {
    let goodsTotal = 0;
    let discountTotal = 0;
    let purchaseTotal = 0;

    form.querySelectorAll('[data-order-item-row]').forEach((row) => {
      if (row.hidden) {
        return;
      }
      const quantity = parseMoney(row.querySelector('[name$="-quantity"]')?.value);
      const salePrice = parseMoney(row.querySelector('[name$="-sale_price"]')?.value);
      const purchasePrice = parseMoney(row.querySelector('[name$="-purchase_price"]')?.value);
      const discount = parseMoney(row.querySelector('[name$="-discount_amount"]')?.value);
      const subtotal = Math.max(salePrice - discount, 0) * quantity;
      goodsTotal += salePrice * quantity;
      purchaseTotal += purchasePrice * quantity;
      discountTotal += discount * quantity;
      const subtotalNode = row.querySelector('[data-item-subtotal]');
      if (subtotalNode) {
        subtotalNode.textContent = formatMoney(subtotal);
      }
    });

    const paidAmount = parseMoney(form.querySelector('[name="prepayment_amount"]')?.value);
    const grandTotal = Math.max(goodsTotal - discountTotal, 0);
    const balanceDue = grandTotal - paidAmount;
    const expectedMargin = Math.max(goodsTotal - discountTotal - purchaseTotal, 0);
    const balanceLabel = form.querySelector('[data-balance-label]');
    if (balanceLabel) {
      balanceLabel.textContent = balanceDue < 0 ? 'Переплата клиенту' : 'Остаток / доплата';
    }

    const summaryFields = {
      goods_total: goodsTotal,
      discount_total: discountTotal,
      expected_margin: expectedMargin,
      grand_total: grandTotal,
      balance_due: Math.abs(balanceDue),
    };
    Object.entries(summaryFields).forEach(([key, value]) => {
      const target = form.querySelector(`[data-summary-field="${key}"]`);
      if (target) {
        target.textContent = formatMoney(value);
      }
    });
  }

  function addManualOrderRow(form) {
    const template = form.querySelector('[data-order-item-template]');
    const totalFormsInput = form.querySelector('[name$="-TOTAL_FORMS"]');
    const itemsContainer = form.querySelector('[data-order-items]');
    if (!template || !totalFormsInput || !itemsContainer) {
      return;
    }
    const nextIndex = Number.parseInt(totalFormsInput.value || '0', 10);
    const html = template.innerHTML.replaceAll('__prefix__', String(nextIndex));
    const wrapper = document.createElement('div');
    wrapper.innerHTML = html.trim();
    const newRow = wrapper.firstElementChild;
    if (!newRow) {
      return;
    }
    itemsContainer.appendChild(newRow);
    totalFormsInput.value = String(nextIndex + 1);
    initManagerPortal(newRow);
    wireManualOrderInteractions(form);
    renumberItemRows(form);
    updateManualOrderSummary(form);
  }

  function removeManualOrderRow(form, row) {
    const deleteInput = row.querySelector('[name$="-DELETE"]');
    if (deleteInput) {
      deleteInput.checked = true;
    }
    row.hidden = true;
    row.querySelectorAll('input, textarea, select').forEach((field) => {
      if (field === deleteInput) {
        return;
      }
      if (field.tagName === 'SELECT') {
        field.selectedIndex = 0;
      } else {
        field.value = '';
      }
    });
    if (!Array.from(form.querySelectorAll('[data-order-item-row]')).some((candidate) => !candidate.hidden)) {
      addManualOrderRow(form);
    }
    renumberItemRows(form);
    updateManualOrderSummary(form);
  }

  function addTradeInRow(form) {
    const template = form.querySelector('[data-tradein-item-template]');
    const totalFormsInput = form.querySelector('[name="tradein-TOTAL_FORMS"]');
    const itemsContainer = form.querySelector('[data-tradein-items]');
    if (!template || !totalFormsInput || !itemsContainer) {
      return;
    }
    const nextIndex = Number.parseInt(totalFormsInput.value || '0', 10);
    const html = template.innerHTML.replaceAll('__prefix__', String(nextIndex));
    const wrapper = document.createElement('div');
    wrapper.innerHTML = html.trim();
    const newRow = wrapper.firstElementChild;
    if (!newRow) {
      return;
    }
    itemsContainer.appendChild(newRow);
    totalFormsInput.value = String(nextIndex + 1);
    initManagerPortal(newRow);
    wireManualOrderInteractions(form);
    renumberTradeInRows(form);
    updateManualOrderSummary(form);
  }

  function removeTradeInRow(form, row) {
    const deleteInput = row.querySelector('[name$="-DELETE"]');
    if (deleteInput) {
      deleteInput.checked = true;
    }
    row.hidden = true;
    row.querySelectorAll('input, textarea, select').forEach((field) => {
      if (field === deleteInput) {
        return;
      }
      if (field.type === 'checkbox') {
        field.checked = false;
      } else if (field.tagName === 'SELECT') {
        field.selectedIndex = 0;
      } else {
        field.value = '';
      }
    });
    renumberTradeInRows(form);
    updateManualOrderSummary(form);
  }

  function wireManualOrderInteractions(scope) {
    const forms = scope.matches?.('[data-manual-order-form]') ? [scope] : scope.querySelectorAll('[data-manual-order-form]');
    forms.forEach((form) => {
      if (form.dataset.managerOrderBound !== '1') {
        form.dataset.managerOrderBound = '1';
        form.addEventListener('input', (event) => {
          if (event.target?.matches?.('[name$="-sale_price"]')) {
            event.target.dataset.catalogAutofilled = '0';
          }
          syncManualOrderProductRows(form);
          updateManualOrderSummary(form);
        });
        form.addEventListener('change', () => {
          syncManualOrderProductRows(form);
          updateDealStatusOptions(form);
          updateManualOrderVisibility(form);
          updateManualOrderSummary(form);
          const dealType = form.querySelector('[name="deal_type"]')?.value;
          const sourceField = form.querySelector('[name="customer_source"]');
          if (dealType === 'avito_sale' && sourceField && ['website', ''].includes(sourceField.value)) {
            sourceField.value = 'avito';
          }
        });
      }

      form.querySelectorAll('[data-order-item-remove]').forEach((button) => {
        if (button.dataset.managerBound === '1') {
          return;
        }
        button.dataset.managerBound = '1';
        button.addEventListener('click', () => {
          const row = button.closest('[data-order-item-row]');
          if (row) {
            removeManualOrderRow(form, row);
          }
        });
      });

      form.querySelectorAll('[data-order-item-add]').forEach((button) => {
        if (button.dataset.managerBound === '1') {
          return;
        }
        button.dataset.managerBound = '1';
        button.addEventListener('click', () => addManualOrderRow(form));
      });

      form.querySelectorAll('[data-tradein-item-remove]').forEach((button) => {
        if (button.dataset.managerBound === '1') {
          return;
        }
        button.dataset.managerBound = '1';
        button.addEventListener('click', () => {
          const row = button.closest('[data-tradein-item-row]');
          if (row) {
            removeTradeInRow(form, row);
          }
        });
      });

      form.querySelectorAll('[data-tradein-item-add]').forEach((button) => {
        if (button.dataset.managerBound === '1') {
          return;
        }
        button.dataset.managerBound = '1';
        button.addEventListener('click', () => addTradeInRow(form));
      });

      syncManualOrderProductRows(form);
      updateDealStatusOptions(form);
      updateManualOrderVisibility(form);
      updateManualOrderSummary(form);
      renumberItemRows(form);
      renumberTradeInRows(form);
    });
  }

  function wireExpandableRows(root) {
    const interactiveSelector = 'a, button, input, select, textarea, label, summary, details, form';

    function toggleRow(rowKey, button) {
      const detailRow = root.querySelector(`[data-row-detail="${rowKey}"]`) || document.querySelector(`[data-row-detail="${rowKey}"]`);
      if (!detailRow) {
        return;
      }
      const isHidden = detailRow.hasAttribute('hidden');
      if (isHidden) {
        detailRow.removeAttribute('hidden');
      } else {
        detailRow.setAttribute('hidden', 'hidden');
      }
      if (button) {
        button.setAttribute('aria-expanded', isHidden ? 'true' : 'false');
        const icon = button.querySelector('[data-row-toggle-icon]');
        if (icon) {
          icon.textContent = isHidden ? '▾' : '▸';
        }
      }
    }

    root.querySelectorAll('[data-row-toggle]').forEach((button) => {
      if (button.dataset.managerBound === '1') {
        return;
      }
      button.dataset.managerBound = '1';
      button.addEventListener('click', (event) => {
        event.stopPropagation();
        toggleRow(button.dataset.rowToggle, button);
      });
    });

    root.querySelectorAll('[data-row-toggle-row]').forEach((row) => {
      if (row.dataset.managerBound === '1') {
        return;
      }
      row.dataset.managerBound = '1';
      row.addEventListener('click', (event) => {
        if (event.target.closest(interactiveSelector)) {
          return;
        }
        const rowKey = row.dataset.rowToggleRow;
        const button = row.querySelector(`[data-row-toggle="${rowKey}"]`) || root.querySelector(`[data-row-toggle="${rowKey}"]`);
        toggleRow(rowKey, button);
      });
    });

  }

  function getTableSortStorage() {
    return getManagerStorage();
  }

  function getSortableTables(root) {
    const tables = [];
    if (root && typeof root.matches === 'function' && root.matches('table')) {
      tables.push(root);
    }
    if (root && typeof root.querySelectorAll === 'function') {
      tables.push(...root.querySelectorAll('table'));
    }
    return tables.filter((table) => table.tHead && table.tBodies && table.tBodies.length);
  }

  function getSortableHeaderCells(table) {
    if (!table.tHead || !table.tHead.rows.length) {
      return [];
    }
    return Array.from(table.tHead.rows[table.tHead.rows.length - 1].cells).filter((cell) => cell.tagName === 'TH');
  }

  function buildTableSortStorageKey(table, headerCells) {
    if (table.dataset.managerSortStorageKey) {
      return table.dataset.managerSortStorageKey;
    }
    const explicitKey = table.id || table.dataset.sortStorageKey || '';
    const headerSignature = headerCells
      .map((cell) => cell.textContent.replace(/\s+/g, ' ').trim())
      .filter(Boolean)
      .join('|');
    const tableIndex = Array.from(document.querySelectorAll('table')).indexOf(table);
    const key = `${TABLE_SORT_STORAGE_PREFIX}${window.location.pathname}:${explicitKey || `${tableIndex}:${headerSignature}`}`;
    table.dataset.managerSortStorageKey = key;
    return key;
  }

  function readStoredTableSort(table, headerCells) {
    const storage = getTableSortStorage();
    if (!storage) {
      return null;
    }
    try {
      const raw = storage.getItem(buildTableSortStorageKey(table, headerCells));
      if (!raw) {
        return null;
      }
      const parsed = JSON.parse(raw);
      const columnIndex = Number(parsed.columnIndex);
      const direction = parsed.direction === 'desc' ? 'desc' : 'asc';
      if (!Number.isInteger(columnIndex) || columnIndex < 0 || columnIndex >= headerCells.length) {
        return null;
      }
      return {columnIndex, direction};
    } catch (error) {
      return null;
    }
  }

  function writeStoredTableSort(table, headerCells, state) {
    const storage = getTableSortStorage();
    if (!storage) {
      return;
    }
    try {
      storage.setItem(buildTableSortStorageKey(table, headerCells), JSON.stringify(state));
    } catch (error) {
      return;
    }
  }

  function extractSortableText(cell) {
    if (!cell) {
      return '';
    }
    const explicitNode = cell.querySelector('[data-sort-value]');
    const explicitValue = cell.dataset.sortValue || explicitNode?.dataset.sortValue || '';
    if (explicitValue) {
      return explicitValue.trim();
    }
    return cell.textContent.replace(/\s+/g, ' ').trim();
  }

  function parseSortableDate(value) {
    const text = String(value || '').trim();
    let match = text.match(/^(\d{2})\.(\d{2})\.(\d{4})(?:\s+(\d{2}):(\d{2}))?$/);
    if (match) {
      const [, day, month, year, hour = '00', minute = '00'] = match;
      return new Date(Number(year), Number(month) - 1, Number(day), Number(hour), Number(minute)).getTime();
    }
    match = text.match(/^(\d{4})-(\d{2})-(\d{2})(?:\s+(\d{2}):(\d{2}))?$/);
    if (match) {
      const [, year, month, day, hour = '00', minute = '00'] = match;
      return new Date(Number(year), Number(month) - 1, Number(day), Number(hour), Number(minute)).getTime();
    }
    return null;
  }

  function parseSortableNumber(value) {
    const text = String(value || '').replace(/[\u00A0\u202F]/g, ' ').trim();
    if (!text || !/^[\s\d.,\-+()%₽$€£]+$/.test(text)) {
      return null;
    }
    const digits = text.replace(/[^\d,.\-+]/g, '');
    if (!digits || !/\d/.test(digits)) {
      return null;
    }
    const lastComma = digits.lastIndexOf(',');
    const lastDot = digits.lastIndexOf('.');
    const decimalIndex = Math.max(lastComma, lastDot);
    let normalized = digits;
    if (decimalIndex !== -1 && digits.length - decimalIndex - 1 <= 2) {
      normalized = `${digits.slice(0, decimalIndex).replace(/[,.]/g, '')}.${digits.slice(decimalIndex + 1).replace(/[,.]/g, '')}`;
    } else {
      normalized = digits.replace(/[,.]/g, '');
    }
    const parsed = Number(normalized);
    return Number.isFinite(parsed) ? parsed : null;
  }

  function buildSortValue(rawValue) {
    const text = String(rawValue || '').replace(/[\u00A0\u202F]/g, ' ').trim();
    if (!text || text === '—') {
      return {kind: 'empty', number: null, text: ''};
    }
    const parsedDate = parseSortableDate(text);
    if (parsedDate !== null) {
      return {kind: 'number', number: parsedDate, text};
    }
    const parsedNumber = parseSortableNumber(text);
    if (parsedNumber !== null) {
      return {kind: 'number', number: parsedNumber, text};
    }
    return {kind: 'text', number: null, text};
  }

  function compareSortValues(left, right) {
    if (left.kind === 'empty' && right.kind === 'empty') {
      return 0;
    }
    if (left.kind === 'empty') {
      return 1;
    }
    if (right.kind === 'empty') {
      return -1;
    }
    if (left.kind === 'number' && right.kind === 'number') {
      return left.number - right.number;
    }
    return sortCollator.compare(left.text, right.text);
  }

  function getRowGroupKey(row) {
    return row.dataset.rowToggleRow || row.querySelector('[data-row-toggle]')?.dataset.rowToggle || '';
  }

  function collectSortableRowGroups(table) {
    const body = table.tBodies[0];
    if (!body) {
      return [];
    }
    const groups = [];
    let currentGroup = null;
    Array.from(body.rows).forEach((row) => {
      const detailKey = row.dataset.rowDetail || '';
      if (detailKey && currentGroup && currentGroup.detailKey === detailKey) {
        currentGroup.rows.push(row);
        return;
      }
      currentGroup = {
        row,
        rows: [row],
        detailKey: getRowGroupKey(row),
      };
      groups.push(currentGroup);
    });
    return groups;
  }

  function isPlaceholderRowGroup(group, columnCount) {
    if (!group || group.rows.length !== 1) {
      return false;
    }
    const row = group.row;
    if (!row || row.dataset.rowDetail) {
      return false;
    }
    if (row.cells.length !== 1) {
      return false;
    }
    const cell = row.cells[0];
    const colSpan = Number(cell.getAttribute('colspan') || '1');
    return colSpan >= Math.max(1, columnCount - 1);
  }

  function updateSortableHeaderState(headerCells, state) {
    headerCells.forEach((cell, index) => {
      const trigger = cell.querySelector('[data-manager-sort-trigger]');
      const indicator = cell.querySelector('[data-manager-sort-indicator]');
      const isActive = Boolean(state) && state.columnIndex === index;
      const direction = isActive ? state.direction : '';
      cell.setAttribute('aria-sort', isActive ? (direction === 'desc' ? 'descending' : 'ascending') : 'none');
      cell.classList.toggle('manager-sortable-header-active', isActive);
      if (trigger) {
        trigger.dataset.sortDirection = direction;
      }
      if (indicator) {
        indicator.textContent = direction === 'desc' ? '↓' : (direction === 'asc' ? '↑' : '');
      }
    });
  }

  function sortTableByColumn(table, headerCells, state, persist = true) {
    const body = table.tBodies[0];
    if (!body) {
      updateSortableHeaderState(headerCells, state);
      return;
    }
    const groups = collectSortableRowGroups(table);
    const columnCount = headerCells.length;
    const dataGroups = [];
    const placeholderGroups = [];

    groups.forEach((group, index) => {
      if (isPlaceholderRowGroup(group, columnCount)) {
        placeholderGroups.push(group);
        return;
      }
      const targetCell = group.row.cells[state.columnIndex];
      dataGroups.push({
        ...group,
        originalIndex: index,
        sortValue: buildSortValue(extractSortableText(targetCell)),
      });
    });

    dataGroups.sort((left, right) => {
      const comparison = compareSortValues(left.sortValue, right.sortValue);
      if (comparison !== 0) {
        if (left.sortValue.kind === 'empty' || right.sortValue.kind === 'empty') {
          return comparison;
        }
        return state.direction === 'desc' ? comparison * -1 : comparison;
      }
      return left.originalIndex - right.originalIndex;
    });

    const fragment = document.createDocumentFragment();
    dataGroups.forEach((group) => {
      group.rows.forEach((row) => fragment.appendChild(row));
    });
    placeholderGroups.forEach((group) => {
      group.rows.forEach((row) => fragment.appendChild(row));
    });
    body.appendChild(fragment);

    table._managerSortState = state;
    updateSortableHeaderState(headerCells, state);
    if (persist) {
      writeStoredTableSort(table, headerCells, state);
    }
  }

  function wireSortableTables(root) {
    getSortableTables(root).forEach((table) => {
      if (table.dataset.managerSortBound === '1') {
        return;
      }
      const headerCells = getSortableHeaderCells(table);
      if (!headerCells.length) {
        return;
      }

      table.dataset.managerSortBound = '1';

      headerCells.forEach((cell, index) => {
        if (cell.dataset.managerSortHeaderBound === '1') {
          return;
        }
        cell.dataset.managerSortHeaderBound = '1';

        const label = document.createElement('span');
        label.className = 'manager-sortable-header-label';
        while (cell.firstChild) {
          label.appendChild(cell.firstChild);
        }

        const indicator = document.createElement('span');
        indicator.className = 'manager-sortable-header-indicator';
        indicator.dataset.managerSortIndicator = '1';
        indicator.setAttribute('aria-hidden', 'true');

        const trigger = document.createElement('button');
        trigger.type = 'button';
        trigger.className = 'manager-sortable-header-trigger cursor-pointer flex items-center gap-1';
        trigger.dataset.managerSortTrigger = '1';
        trigger.append(label, indicator);
        trigger.addEventListener('click', () => {
          const currentState = table._managerSortState;
          const nextState = currentState && currentState.columnIndex === index && currentState.direction === 'asc'
            ? {columnIndex: index, direction: 'desc'}
            : {columnIndex: index, direction: 'asc'};
          sortTableByColumn(table, headerCells, nextState);
        });

        cell.textContent = '';
        cell.appendChild(trigger);
      });

      const storedState = readStoredTableSort(table, headerCells);
      if (storedState) {
        sortTableByColumn(table, headerCells, storedState, false);
      } else {
        updateSortableHeaderState(headerCells, null);
      }
    });
  }

  function wireTabs(root) {
    root.querySelectorAll('[data-manager-tabs]').forEach((container) => {
      if (container.dataset.tabsBound === '1') {
        return;
      }
      container.dataset.tabsBound = '1';
      const buttons = Array.from(container.querySelectorAll('[data-tab-target]'));
      const panels = Array.from(container.querySelectorAll('[data-tab-panel]'));
      if (!buttons.length || !panels.length) {
        return;
      }
      const urlKey = container.dataset.tabUrlKey || '';

      const setActiveTab = (target, options = {}) => {
        const fallbackTarget = buttons[0].dataset.tabTarget;
        const normalizedTarget = buttons.some((button) => button.dataset.tabTarget === target) ? target : fallbackTarget;
        const shouldSyncUrl = options.syncUrl !== false && urlKey;
        buttons.forEach((button) => {
          const isActive = button.dataset.tabTarget === normalizedTarget;
          button.classList.toggle('border-cyan-400', isActive);
          button.classList.toggle('bg-cyan-500/10', isActive);
          button.classList.toggle('text-white', isActive);
          button.classList.toggle('border-slate-700', !isActive);
          button.classList.toggle('text-slate-400', !isActive);
          button.classList.toggle('hover:bg-slate-900/80', !isActive);
          button.setAttribute('aria-selected', isActive ? 'true' : 'false');
        });
        panels.forEach((panel) => {
          const isActive = panel.dataset.tabPanel === normalizedTarget;
          panel.toggleAttribute('hidden', !isActive);
        });
        if (shouldSyncUrl) {
          const url = new URL(window.location.href);
          url.searchParams.set(urlKey, normalizedTarget);
          window.history.replaceState({}, '', `${url.pathname}${url.search}${url.hash}`);
        }
      };
      container._managerSetActiveTab = setActiveTab;

      buttons.forEach((button) => {
        button.setAttribute('role', 'tab');
        button.addEventListener('click', () => setActiveTab(button.dataset.tabTarget));
      });
      panels.forEach((panel) => panel.setAttribute('role', 'tabpanel'));

      const initialTarget = (
        (urlKey ? new URL(window.location.href).searchParams.get(urlKey) : '')
        || container.dataset.tabInitial
        || buttons[0].dataset.tabTarget
      );
      setActiveTab(initialTarget, {syncUrl: false});
    });
  }

  function syncTabsWithHash() {
    const hash = window.location.hash;
    if (!hash) {
      return;
    }
    let target = null;
    try {
      target = document.querySelector(hash);
    } catch (error) {
      return;
    }
    if (!target) {
      return;
    }

    let panel = target.closest('[data-tab-panel]');
    while (panel) {
      const container = panel.closest('[data-manager-tabs]');
      if (!container || typeof container._managerSetActiveTab !== 'function') {
        break;
      }
      container._managerSetActiveTab(panel.dataset.tabPanel);
      panel = container.parentElement ? container.parentElement.closest('[data-tab-panel]') : null;
    }
  }

  function syncTabsWithSearch() {
    document.querySelectorAll('[data-manager-tabs][data-tab-url-key]').forEach((container) => {
      if (typeof container._managerSetActiveTab !== 'function') {
        return;
      }
      const url = new URL(window.location.href);
      const urlKey = container.dataset.tabUrlKey;
      const target = url.searchParams.get(urlKey);
      if (!target) {
        return;
      }
      const hasTarget = container.querySelector(`[data-tab-target="${target}"]`);
      if (!hasTarget) {
        return;
      }
      container._managerSetActiveTab(target, {syncUrl: false});
    });
  }

  function wireDealBoard(root) {
    const board = root.matches?.('[data-manager-deal-board]')
      ? root
      : root.querySelector('[data-manager-deal-board]');
    if (!board) {
      return;
    }
    const viewport = board.querySelector('[data-board-viewport]');
    const scroller = board.querySelector('[data-board-scroller]');
    const controlsScope = root.matches?.('[data-manager-deal-board]') ? document : root;
    const navEl = controlsScope.querySelector('[data-kanban-nav]');
    const indicatorEl = navEl?.querySelector('[data-nav-indicator]');
    const prevLabelEl = navEl?.querySelector('[data-nav-prev-label]');
    const nextLabelEl = navEl?.querySelector('[data-nav-next-label]');
    const prevBtn = controlsScope.querySelector('[data-board-scroll="prev"]');
    const nextBtn = controlsScope.querySelector('[data-board-scroll="next"]');

    const allColumns = board ? Array.from(board.querySelectorAll('[data-kanban-column]')) : [];
    const totalColumns = allColumns.length;

    const updateNavState = () => {
      if (!viewport || !totalColumns) return;
      // Find the first column whose left edge is at or past the viewport's left edge
      const viewportLeft = viewport.scrollLeft;
      const viewportRight = viewportLeft + viewport.clientWidth;
      let firstVisible = 0;
      for (let i = 0; i < allColumns.length; i++) {
        if (allColumns[i].offsetLeft + allColumns[i].offsetWidth / 2 >= viewportLeft) {
          firstVisible = i;
          break;
        }
      }
      const displayIndex = firstVisible + 1;
      if (indicatorEl) {
        indicatorEl.textContent = `Этап ${displayIndex} из ${totalColumns}`;
      }
      if (prevLabelEl) {
        prevLabelEl.textContent = firstVisible > 0 ? allColumns[firstVisible - 1].dataset.columnLabel || '' : '';
      }
      if (nextLabelEl) {
        const nextIdx = firstVisible + 1;
        nextLabelEl.textContent = nextIdx < totalColumns ? allColumns[nextIdx].dataset.columnLabel || '' : '';
      }
      if (prevBtn) prevBtn.disabled = viewportLeft <= 0;
      if (nextBtn) nextBtn.disabled = viewportRight >= viewport.scrollWidth - 2;
      // Fade: hide right fade when scrolled to end
      if (scroller) {
        scroller.classList.toggle('is-at-end', viewportRight >= viewport.scrollWidth - 8);
      }
    };

    if (viewport) {
      viewport.addEventListener('scroll', updateNavState, {passive: true});
      updateNavState();
    }

    controlsScope.querySelectorAll('[data-board-scroll]').forEach((button) => {
      if (button.dataset.managerBound === '1') {
        return;
      }
      button.dataset.managerBound = '1';
      button.addEventListener('click', () => {
        if (!viewport) {
          return;
        }
        const direction = button.dataset.boardScroll === 'prev' ? -1 : 1;
        // Scroll by exactly one column width
        const firstCol = allColumns[0];
        const colWidth = firstCol ? firstCol.offsetWidth + 11 : Math.max(Math.round(viewport.clientWidth * 0.92), 280);
        viewport.scrollBy({left: direction * colWidth, behavior: 'smooth'});
      });
    });

    // Drag-scroll with mouse on desktop
    if (viewport && !viewport.dataset.dragScrollBound) {
      viewport.dataset.dragScrollBound = '1';
      let isDragging = false;
      let startX = 0;
      let startScrollLeft = 0;
      viewport.addEventListener('mousedown', (e) => {
        // Only initiate drag if not clicking a card link or button
        if (e.target.closest('a, button, [draggable="true"]')) return;
        isDragging = true;
        startX = e.clientX;
        startScrollLeft = viewport.scrollLeft;
        viewport.style.cursor = 'grabbing';
        viewport.style.userSelect = 'none';
      });
      document.addEventListener('mousemove', (e) => {
        if (!isDragging) return;
        const dx = e.clientX - startX;
        viewport.scrollLeft = startScrollLeft - dx;
      });
      document.addEventListener('mouseup', () => {
        if (!isDragging) return;
        isDragging = false;
        viewport.style.cursor = '';
        viewport.style.userSelect = '';
      });
    }

    let draggingCard = null;
    const csrfToken = getCookie('csrftoken');

    const parseHtml = (html) => {
      const template = document.createElement('template');
      template.innerHTML = String(html || '').trim();
      return template.content.firstElementChild;
    };

    const syncColumnState = (column) => {
      const body = column.querySelector('[data-kanban-column-body]');
      const count = column.querySelector('[data-kanban-count]');
      const emptyState = column.querySelector('[data-kanban-empty]');
      if (!body || !count) {
        return;
      }
      const cardsCount = body.querySelectorAll('[data-deal-card]').length;
      count.textContent = String(cardsCount);
      if (emptyState) {
        emptyState.classList.toggle('hidden', cardsCount > 0);
        emptyState.hidden = cardsCount > 0;
      }
    };

    const moveCard = async (card, targetColumn) => {
      const targetStatus = targetColumn.dataset.caseStatus;
      if (!card || !targetStatus || card.dataset.caseStatus === targetStatus || card.classList.contains('is-updating')) {
        return;
      }
      const moveUrl = card.dataset.moveUrl;
      if (!moveUrl) {
        return;
      }
      card.classList.add('is-updating');
      try {
        const response = await fetch(moveUrl, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'X-CSRFToken': csrfToken,
            'X-Requested-With': 'XMLHttpRequest',
          },
          body: new URLSearchParams({
            case_status: targetStatus,
            return_query: board.dataset.returnQuery || '',
          }).toString(),
        });
        const payload = await response.json();
        if (!response.ok || !payload.ok) {
          throw new Error(payload.error || `Deal move failed: ${response.status}`);
        }
        const replacement = parseHtml(payload.html);
        if (!replacement) {
          throw new Error('Deal card HTML is empty');
        }
        const sourceColumn = card.closest('[data-kanban-column]');
        const targetBody = targetColumn.querySelector('[data-kanban-column-body]');
        if (!targetBody) {
          throw new Error('Deal column body not found');
        }
        targetBody.appendChild(replacement);
        card.remove();
        syncColumnState(targetColumn);
        if (sourceColumn) {
          syncColumnState(sourceColumn);
        }
        if (typeof window.initManagerPortal === 'function') {
          window.initManagerPortal(board);
        }
      } catch (error) {
        window.console.error(error);
        window.alert('Не удалось переместить сделку. Обновите страницу и повторите попытку.');
        card.classList.remove('is-updating');
      }
    };

    board.querySelectorAll('[data-deal-card]').forEach((card) => {
      if (card.dataset.boardBound === '1') {
        return;
      }
      card.dataset.boardBound = '1';
      card.addEventListener('dragstart', (event) => {
        draggingCard = card;
        card.classList.add('is-dragging');
        if (event.dataTransfer) {
          event.dataTransfer.effectAllowed = 'move';
          event.dataTransfer.setData('text/plain', card.dataset.dealId || '');
        }
      });
      card.addEventListener('dragend', () => {
        card.classList.remove('is-dragging');
        draggingCard = null;
        board.querySelectorAll('[data-kanban-column]').forEach((column) => {
          column.classList.remove('is-drop-target');
        });
      });

      // Progressive disclosure: expand/collapse card details
      const expandBtn = card.querySelector('[data-card-expand]');
      const detailsEl = card.querySelector('[data-card-details]');
      if (expandBtn && detailsEl) {
        expandBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          const expanded = expandBtn.getAttribute('aria-expanded') === 'true';
          expandBtn.setAttribute('aria-expanded', String(!expanded));
          detailsEl.hidden = expanded;
        });
      }
    });

    board.querySelectorAll('[data-kanban-column]').forEach((column) => {
      if (column.dataset.boardBound === '1') {
        syncColumnState(column);
        return;
      }
      column.dataset.boardBound = '1';
      syncColumnState(column);
      column.addEventListener('dragover', (event) => {
        if (!draggingCard) {
          return;
        }
        event.preventDefault();
        column.classList.add('is-drop-target');
      });
      column.addEventListener('dragleave', (event) => {
        if (!column.contains(event.relatedTarget)) {
          column.classList.remove('is-drop-target');
        }
      });
      column.addEventListener('drop', async (event) => {
        event.preventDefault();
        column.classList.remove('is-drop-target');
        await moveCard(draggingCard, column);
      });
    });
  }

  function initManagerPortal(root = document) {
    wireThemeToggle(root);
    wireNavigationProgress();
    wireDesktopSidebar(root);
    wireClientFilters(root);
    wireDatePickers(root);
    wireFieldMasks(root);
    wireDatePickerTriggers(root);
    wireDisclosureToggles(root);
    wireAutoFilters(root);
    wireDealFilterToggles(root);
    wireBulkSelection(root);
    wireScrollFade(root);
    wireFilterSearch(root);
    wireDrawers(root);
    wireRemoteDrawer(root);
    wireMessages(root);
    wireMobileSidebar(root);
    wireCopyActions(root);
    wireGlobalSearchOverlay(root);
    wireManualOrderInteractions(root);
    wireExpandableRows(root);
    wireSortableTables(root);
    wireDealBoard(root);
    wireTabs(root);
    wireFinanceCashflowChart(root);
    syncTabsWithSearch();
    syncTabsWithHash();
    wireGlobalSearch(document);
  }

  document.addEventListener('click', (event) => {
    if (event.target.matches('[data-drawer-overlay]')) {
      closeDrawers();
    }
    if (globalSearchState && event.target.matches('[data-manager-global-search-backdrop]')) {
      closeGlobalSearch(globalSearchState);
      return;
    }
    if (
      globalSearchState
      && !globalSearchState.form.contains(event.target)
      && !globalSearchState.panel.contains(event.target)
    ) {
      closeGlobalSearch(globalSearchState);
    }
  });

  document.addEventListener('keydown', (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
      event.preventDefault();
      focusGlobalSearchInput();
      return;
    }
    if (event.key === '/' && !event.metaKey && !event.ctrlKey && !event.altKey && !isEditableTarget(event.target)) {
      event.preventDefault();
      focusGlobalSearchInput();
      return;
    }
    if (event.key === 'Escape') {
      if (globalSearchState) {
        closeGlobalSearch(globalSearchState);
      }
      closeGlobalSearchOverlay();
      closeDrawers();
    }
  });

  window.addEventListener('resize', () => {
    syncDesktopSidebarToggleState();
  });

  window.addEventListener('hashchange', syncTabsWithHash);
  window.addEventListener('popstate', () => {
    syncTabsWithSearch();
    syncTabsWithHash();
  });
  window.addEventListener('storage', (event) => {
    if (event.key && event.key !== MANAGER_THEME_STORAGE_KEY) {
      return;
    }
    applyManagerTheme(event.newValue || MANAGER_DEFAULT_THEME, {persist: false});
  });

  window.addEventListener('pageshow', completeNavigationProgress);

  document.addEventListener('DOMContentLoaded', () => {
    applyManagerTheme(managerTheme, {persist: false});
    completeNavigationProgress();
    initManagerPortal(document);
  });

  document.addEventListener('htmx:afterSwap', (event) => {
    const remoteDrawerTarget = document.querySelector('#manager-remote-drawer-content');
    if (remoteDrawerTarget && event.target === remoteDrawerTarget && event.detail && event.detail.xhr) {
      remoteDrawerTarget.dataset.currentUrl = event.detail.xhr.responseURL || '';
    }
    initManagerPortal(event.target);
    if (typeof window.initLucide === 'function') {
      window.initLucide();
    }
  });

  window.initManagerPortal = initManagerPortal;
})();
