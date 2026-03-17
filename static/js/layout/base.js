    let lucideRetryTimer = null;
    let lucideObserverStarted = false;

    window.catalogProductList = window.catalogProductList || function catalogProductList() {
      return {
        filtersModalOpen: false,
        sortDropdownOpen: false,
        mobileFiltersDirty: false,
        pendingFiltersUrl: '',

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
          const minVal = scope.querySelector('input[type=number][name=price_min]')?.value ?? '';
          const maxVal = scope.querySelector('input[type=number][name=price_max]')?.value ?? '';

          if (minVal) url.searchParams.set('price_min', minVal);
          else url.searchParams.delete('price_min');

          if (maxVal) url.searchParams.set('price_max', maxVal);
          else url.searchParams.delete('price_max');

          window.location.href = url.toString();
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

    function scheduleLucideRetry(delay = 0) {
      if (lucideRetryTimer) {
        window.clearTimeout(lucideRetryTimer);
      }
      lucideRetryTimer = window.setTimeout(() => {
        lucideRetryTimer = null;
        initLucide(true);
      }, delay);
    }

    function hasPendingLucideIcons(node) {
      if (!(node instanceof Element)) {
        return false;
      }
      return node.hasAttribute('data-lucide') || Boolean(node.querySelector('[data-lucide]'));
    }

    // Инициализация Lucide иконок после загрузки HTMX контента
    function initLucide(fromRetry = false) {
      if (typeof window === 'undefined') {
        return false;
      }

      if (!window.lucide || typeof window.lucide.createIcons !== 'function') {
        if (!fromRetry) {
          scheduleLucideRetry(120);
        }
        return false;
      }

      window.lucide.createIcons();
      return true;
    }

    function ensureLucideObserver() {
      if (
        lucideObserverStarted
        || typeof window === 'undefined'
        || typeof MutationObserver === 'undefined'
        || !document.body
      ) {
        return;
      }

      const observer = new MutationObserver((mutations) => {
        const shouldInit = mutations.some((mutation) =>
          Array.from(mutation.addedNodes || []).some((node) => hasPendingLucideIcons(node))
        );

        if (shouldInit) {
          scheduleLucideRetry(0);
        }
      });

      observer.observe(document.body, { childList: true, subtree: true });
      lucideObserverStarted = true;
    }

    window.initLucide = initLucide;
    
    function scrollToTop() {
      document.documentElement.scrollTop = 0;
      document.body.scrollTop = 0;
      window.scrollTo({ top: 0, left: 0, behavior: 'auto' });
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

    function normalizePhoneDigits(value) {
      let digits = (value || '').replace(/\D/g, '');
      if (digits.length === 11 && (digits[0] === '7' || digits[0] === '8')) {
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

    function getCaretPositionByDigits(formattedValue, digitsBeforeCaret) {
      if (digitsBeforeCaret <= 0) return 0;

      let seenDigits = 0;
      for (let index = 0; index < formattedValue.length; index += 1) {
        if (/\d/.test(formattedValue[index])) {
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
        const syncValue = preserveCaret => {
          const currentValue = input.value || '';
          const selectionStart = typeof input.selectionStart === 'number' ? input.selectionStart : currentValue.length;
          const digitsBeforeCaret = normalizePhoneDigits(currentValue.slice(0, selectionStart)).length;
          const digits = normalizePhoneDigits(currentValue);
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
            const caretPosition = getCaretPositionByDigits(formattedValue, digitsBeforeCaret);
            requestAnimationFrame(() => input.setSelectionRange(caretPosition, caretPosition));
          }
        };

        if (!input.dataset.phoneMaskBound) {
          input.addEventListener('input', () => syncValue(true));
          input.addEventListener('focus', () => syncValue(true));
          input.addEventListener('blur', () => syncValue(false));
          input.dataset.phoneMaskBound = '1';
        }

        syncValue(false);
      });
    }

    const LOADING_SKELETON_TARGET_SELECTOR = '#main-content, #manager-main-content';
    const LOADING_SKELETON_SCOPE_CLASS = 'bizon-loading-scope';
    const LOADING_SKELETON_ACTIVE_CLASS = 'is-loading';

    function isLoadingSkeletonTarget(target) {
      return target instanceof Element && target.matches(LOADING_SKELETON_TARGET_SELECTOR);
    }

    function getLoadingSkeletonRoots(root) {
      if (root instanceof Element) {
        if (isLoadingSkeletonTarget(root)) {
          return [root];
        }
        return Array.from(root.querySelectorAll(LOADING_SKELETON_TARGET_SELECTOR));
      }
      return Array.from(document.querySelectorAll(LOADING_SKELETON_TARGET_SELECTOR));
    }

    function uniqueElements(elements) {
      return Array.from(new Set(elements.filter((element) => element instanceof Element)));
    }

    function buildTableSkeletonMarkup(rowCount, columnCount) {
      const safeRowCount = Math.max(4, rowCount || 0);
      const safeColumnCount = Math.max(3, columnCount || 0);
      const buildColumns = () => {
        const columns = [];
        for (let columnIndex = 0; columnIndex < safeColumnCount; columnIndex += 1) {
          columns.push('<span class="bizon-skeleton-line bizon-skeleton-line-table"></span>');
        }
        return columns.join('');
      };
      const rows = [];

      for (let rowIndex = 0; rowIndex < safeRowCount; rowIndex += 1) {
        rows.push(`<div class="bizon-table-skeleton-row">${buildColumns()}</div>`);
      }

      return `
        <div class="bizon-table-skeleton">
          <div class="bizon-table-skeleton-row bizon-table-skeleton-row-head">${buildColumns()}</div>
          <div class="bizon-table-skeleton-body">${rows.join('')}</div>
        </div>
      `;
    }

    function buildCardSkeletonMarkup(cardCount) {
      const safeCardCount = Math.max(3, cardCount || 0);
      const cards = [];

      for (let index = 0; index < safeCardCount; index += 1) {
        cards.push('<div class="bizon-card-skeleton-item bizon-skeleton-pulse"></div>');
      }

      return `<div class="bizon-card-skeleton">${cards.join('')}</div>`;
    }

    function syncLoadingSkeletonScope(scope) {
      if (!(scope instanceof Element)) {
        return;
      }

      const overlay = scope.querySelector(':scope > .bizon-loading-overlay');
      if (!overlay) {
        return;
      }

      const type = scope.dataset.bizonLoadingScope || '';
      const minHeight = Math.max(scope.clientHeight, 180);
      overlay.style.minHeight = `${minHeight}px`;

      if (type !== 'table') {
        return;
      }

      const table = scope.querySelector('table');
      const skeleton = overlay.querySelector('.bizon-table-skeleton');
      if (!table || !skeleton) {
        return;
      }

      const tableWidth = Math.max(scope.clientWidth, table.scrollWidth, 640);
      const tableHeight = Math.max(scope.clientHeight, table.offsetHeight, 220);

      skeleton.style.setProperty('--bizon-table-skeleton-columns', String(
        Math.min(Math.max(table.tHead?.rows?.[0]?.cells?.length || table.rows?.[0]?.cells?.length || 0, 3), 6)
      ));
      skeleton.style.width = `${tableWidth}px`;
      overlay.style.minHeight = `${tableHeight}px`;
    }

    function ensureLoadingSkeletonScope(scope, type, options = {}) {
      if (!(scope instanceof Element) || scope.dataset.bizonLoadingScope === type) {
        if (scope instanceof Element && scope.dataset.bizonLoadingScope === type) {
          syncLoadingSkeletonScope(scope);
        }
        return;
      }

      if (scope.dataset.bizonLoadingScope) {
        return;
      }

      scope.dataset.bizonLoadingScope = type;
      scope.classList.add(LOADING_SKELETON_SCOPE_CLASS, `bizon-loading-scope-${type}`);

      const overlay = document.createElement('div');
      overlay.className = `bizon-loading-overlay bizon-loading-overlay-${type}`;
      overlay.setAttribute('aria-hidden', 'true');

      if (type === 'table') {
        overlay.innerHTML = buildTableSkeletonMarkup(options.rowCount, options.columnCount);
      } else {
        overlay.innerHTML = buildCardSkeletonMarkup(options.cardCount);
      }

      scope.appendChild(overlay);
      syncLoadingSkeletonScope(scope);
    }

    function prepareLoadingSkeletons(root) {
      getLoadingSkeletonRoots(root).forEach((targetRoot) => {
        targetRoot.querySelectorAll('table').forEach((table) => {
          const scope = table.closest('.overflow-x-auto') || table.parentElement;
          if (!scope || !targetRoot.contains(scope)) {
            return;
          }

          const bodyRows = table.tBodies[0]?.rows?.length || 0;
          const columns = table.tHead?.rows?.[0]?.cells?.length || table.rows?.[0]?.cells?.length || 0;

          ensureLoadingSkeletonScope(scope, 'table', {
            rowCount: Math.min(Math.max(bodyRows, 4), 8),
            columnCount: Math.min(Math.max(columns, 3), 6),
          });
        });

        const mobileCardContainers = uniqueElements(
          Array.from(targetRoot.querySelectorAll('.manager-mobile-deal-card')).map((card) => card.parentElement)
        );

        mobileCardContainers.forEach((container) => {
          ensureLoadingSkeletonScope(container, 'cards', {
            cardCount: Math.min(Math.max(container.querySelectorAll('.manager-mobile-deal-card').length, 3), 5),
          });
        });

        targetRoot.querySelectorAll('[data-kanban-column-body]').forEach((container) => {
          ensureLoadingSkeletonScope(container, 'cards', {
            cardCount: Math.min(Math.max(container.querySelectorAll('.manager-deal-card').length, 3), 4),
          });
        });
      });
    }

    function showLoadingSkeletons(root) {
      getLoadingSkeletonRoots(root).forEach((targetRoot) => {
        prepareLoadingSkeletons(targetRoot);
        targetRoot.querySelectorAll(`.${LOADING_SKELETON_SCOPE_CLASS}`).forEach((scope) => {
          syncLoadingSkeletonScope(scope);
          scope.classList.add(LOADING_SKELETON_ACTIVE_CLASS);
        });
      });
    }

    function clearLoadingSkeletons(root) {
      getLoadingSkeletonRoots(root).forEach((targetRoot) => {
        targetRoot.querySelectorAll(`.${LOADING_SKELETON_SCOPE_CLASS}`).forEach((scope) => {
          scope.classList.remove(LOADING_SKELETON_ACTIVE_CLASS);
        });
      });
    }

    window.bizonLoadingSkeletons = {
      clear: clearLoadingSkeletons,
      prepare: prepareLoadingSkeletons,
      show: showLoadingSkeletons,
    };
    
    function initHtmxHandlers() {
      initLucide(); // иконки в шапке (каталог и др.) сразу при загрузке
      ensureLucideObserver();
      initPhoneMasks(document);
      initCookieConsentBanner();
      prepareLoadingSkeletons(document);
      // Проверяем, что body уже существует
      if (!document.body) {
        console.warn('document.body is not available yet');
        return;
      }
      
      document.body.addEventListener('htmx:beforeRequest', function(ev) {
        if (isLoadingSkeletonTarget(ev.detail.target)) {
          showLoadingSkeletons(ev.detail.target);
        }
      });
      document.body.addEventListener('htmx:beforeSwap', function(ev) {
        // Обновляем data-active-section перед заменой контента
        if (ev.detail.target.id === 'main-content') {
          const parser = new DOMParser();
          const doc = parser.parseFromString(ev.detail.xhr.responseText, 'text/html');
          const newActiveSection = doc.body.dataset.activeSection;
          if (newActiveSection) {
            document.body.dataset.activeSection = newActiveSection;
          }
        }
      });
      document.body.addEventListener('htmx:afterSettle', function(ev) {
        scheduleLucideRetry(0);
        initPhoneMasks(document);
        // После полного обновления DOM
        if (ev.detail.target.id === 'main-content') {
          window.dispatchEvent(new CustomEvent('header-expand'));
          // Для обычных переходов всегда начинаем страницу сверху.
          // Если нужно спец-восстановление (каталог -> карточка -> назад),
          // отдельный обработчик ниже восстановит сохранённую позицию.
          scrollToTop();
          // Обновляем активную вкладку в мобильном меню
          updateActiveDockItem();
        }
        if (isLoadingSkeletonTarget(ev.detail.target)) {
          prepareLoadingSkeletons(ev.detail.target);
        }
      });
      document.body.addEventListener('htmx:afterSwap', function(ev) {
        if (isLoadingSkeletonTarget(ev.detail.target)) {
          prepareLoadingSkeletons(ev.detail.target);
        }
        if (ev.detail.target.id === 'main-content') {
          // НЕ скроллим вверх автоматически - позицию восстановит скрипт ниже
          // Alpine.js автоматически обнаружит новые элементы с x-data через MutationObserver
          // Поэтому initTree вызывать не обязательно и это может вызвать ошибки
          scheduleLucideRetry(0);
          initPhoneMasks(document);
        }
      });
      document.body.addEventListener('htmx:responseError', function(ev) {
        if (isLoadingSkeletonTarget(ev.detail.target)) {
          clearLoadingSkeletons(ev.detail.target);
        }
      });
      document.body.addEventListener('htmx:sendError', function(ev) {
        if (isLoadingSkeletonTarget(ev.detail.target)) {
          clearLoadingSkeletons(ev.detail.target);
        }
      });
      document.body.addEventListener('htmx:timeout', function(ev) {
        if (isLoadingSkeletonTarget(ev.detail.target)) {
          clearLoadingSkeletons(ev.detail.target);
        }
      });
      
      // Обновляем активную вкладку при первой загрузке
      updateActiveDockItem();
    }
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', initHtmxHandlers);
    } else {
      initHtmxHandlers();
    }
    window.addEventListener('load', () => {
      scheduleLucideRetry(0);
    });

    // Сохраняем скролл только для сценария:
    // список каталога -> карточка товара -> возврат в тот же список.
    (function() {
      const STORAGE_KEY = 'bizonvr_catalog_list_return_scroll';
      let pendingNavigation = null;

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
