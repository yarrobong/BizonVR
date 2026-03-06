    // Инициализация Lucide иконок после загрузки HTMX контента
    function initLucide() {
      if (typeof lucide !== 'undefined') {
        lucide.createIcons();
      }
    }
    
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

    function initPhonePrefixBrackets(root) {
      const scope = root || document;
      const wrappers = scope.querySelectorAll('.phone-input-wrapper');

      wrappers.forEach(wrapper => {
        const input = wrapper.querySelector('.js-phone-mask');
        const bracket = wrapper.querySelector('.phone-prefix-bracket');
        if (!input || !bracket) return;

        const updateBracketVisibility = () => {
          const hasDigits = (input.value || '').replace(/\D/g, '').length > 0;
          bracket.style.display = hasDigits ? '' : 'none';
        };

        if (!input.dataset.phoneBracketBound) {
          input.addEventListener('input', updateBracketVisibility);
          input.dataset.phoneBracketBound = '1';
        }

        updateBracketVisibility();
      });
    }
    
    function initHtmxHandlers() {
      initLucide(); // иконки в шапке (каталог и др.) сразу при загрузке
      initPhonePrefixBrackets(document);
      initCookieConsentBanner();
      // Проверяем, что body уже существует
      if (!document.body) {
        console.warn('document.body is not available yet');
        return;
      }
      
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
        initLucide();
        initPhonePrefixBrackets(document);
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
      });
      document.body.addEventListener('htmx:afterSwap', function(ev) {
        if (ev.detail.target.id === 'main-content') {
          // НЕ скроллим вверх автоматически - позицию восстановит скрипт ниже
          // Alpine.js автоматически обнаружит новые элементы с x-data через MutationObserver
          // Поэтому initTree вызывать не обязательно и это может вызвать ошибки
          initLucide();
          initPhonePrefixBrackets(document);
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
