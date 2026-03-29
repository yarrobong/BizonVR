    let lucideRetryTimer = null;
    let lucideObserverStarted = false;

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
    
    function initHtmxHandlers() {
      function syncLayoutState() {
        const mainContent = document.getElementById('main-content');
        const stickyHeaderMarker = mainContent?.querySelector('[data-layout-sticky-header]');
        const stickyHeaderEnabled = stickyHeaderMarker?.dataset.layoutStickyHeader !== 'off';

        window.dispatchEvent(new CustomEvent('layout-sticky-header', {
          detail: { enabled: stickyHeaderEnabled }
        }));
      }

      initLucide(); // иконки в шапке (каталог и др.) сразу при загрузке
      ensureLucideObserver();
      initPhoneMasks(document);
      initCookieConsentBanner();
      syncLayoutState();
      // Проверяем, что body уже существует
      if (!document.body) {
        console.warn('document.body is not available yet');
        return;
      }

      document.body.addEventListener('htmx:beforeRequest', function(ev) {
        if (ev.detail.target?.id !== 'main-content') return;

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
          const newActiveSection = doc.body.dataset.activeSection;
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
        scheduleLucideRetry(0);
        initPhoneMasks(document);
        // После полного обновления DOM
        if (ev.detail.target.id === 'main-content') {
          syncLayoutState();
          window.dispatchEvent(new CustomEvent('header-expand'));
          const mainContent = document.getElementById('main-content');
          if (mainContent) {
            mainContent.style.minHeight = '';
          }
          // Обновляем активную вкладку в мобильном меню
          updateActiveDockItem();
        }
        // Manager portal: scroll to top after navigation
        if (ev.detail.target.id === 'manager-main-content') {
          scrollToTop();
        }
      });
      document.body.addEventListener('htmx:afterSwap', function(ev) {
        if (ev.detail.target.id === 'main-content') {
          // НЕ скроллим вверх автоматически - позицию восстановит скрипт ниже
          // Alpine.js автоматически обнаружит новые элементы с x-data через MutationObserver
          // Поэтому initTree вызывать не обязательно и это может вызвать ошибки
          syncLayoutState();
          scheduleLucideRetry(0);
          initPhoneMasks(document);
        }
        if (ev.detail.target.id === 'manager-main-content') {
          scheduleLucideRetry(0);
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
