(function () {
  const configNode = document.getElementById('cdek-widget-config');
  const checkoutForm = document.getElementById('checkout-form');
  if (!configNode || !checkoutForm) {
    return;
  }

  let config = {};
  try {
    config = JSON.parse(configNode.textContent || '{}');
  } catch (error) {
    window.console.error('Failed to parse CDEK widget config', error);
    return;
  }

  if (!config.enabled || typeof window.CDEKWidget !== 'function') {
    return;
  }

  const desktopMedia = window.matchMedia('(min-width: 768px)');
  const summary = document.getElementById('cdek-selection-summary');
  const mobileModal = document.getElementById('cdek-widget-mobile-modal');
  const openMobileButton = document.querySelector('[data-cdek-open-mobile]');
  const closeMobileButton = document.querySelector('[data-cdek-close-mobile]');
  const changeButton = document.querySelector('[data-cdek-change]');
  const cityInput = document.getElementById('id_city_text');
  const addressInput = document.getElementById('id_address_line');
  const officeRawInput = document.getElementById('id_cdek_office_snapshot_raw');
  const tariffRawInput = document.getElementById('id_cdek_tariff_snapshot_raw');
  const inlineRootId = 'cdek-widget-inline-root';
  const mobileRootId = 'cdek-widget-mobile-root';

  const state = {
    desktopWidget: null,
    mobileWidget: null,
    initializedMode: null,
  };

  function parseSnapshot(rawValue) {
    if (!rawValue) {
      return null;
    }
    try {
      const parsed = JSON.parse(rawValue);
      return parsed && typeof parsed === 'object' ? parsed : null;
    } catch (error) {
      return null;
    }
  }

  function formatLegacyAddress(office) {
    const code = office.code || '';
    const name = office.name || '';
    const address = office.address || '';
    if (code && name && address) {
      return code + ' — ' + name + ', ' + address;
    }
    return [code, name, address].filter(Boolean).join(', ');
  }

  function setSummaryValue(selector, value, fallback) {
    const node = summary ? summary.querySelector(selector) : null;
    if (node) {
      node.textContent = value || fallback;
    }
  }

  function renderSummary(office) {
    if (!summary) {
      return;
    }
    if (!office) {
      summary.classList.add('hidden');
      return;
    }
    summary.classList.remove('hidden');
    setSummaryValue('[data-cdek-city]', office.city, 'Не выбран');
    setSummaryValue('[data-cdek-code]', office.code, '—');
    setSummaryValue('[data-cdek-name]', office.name, '—');
    setSummaryValue('[data-cdek-address]', office.address, '—');
    setSummaryValue('[data-cdek-work-time]', office.work_time, 'Уточним у СДЭК');
  }

  function syncHiddenFields(office, tariff) {
    if (!office || !officeRawInput || !cityInput || !addressInput) {
      return;
    }
    officeRawInput.value = JSON.stringify(office);
    if (tariffRawInput) {
      tariffRawInput.value = tariff ? JSON.stringify(tariff) : '';
    }
    cityInput.value = office.city || '';
    addressInput.value = formatLegacyAddress(office);
  }

  function closeMobileModal() {
    if (!mobileModal) {
      return;
    }
    mobileModal.classList.add('hidden');
    mobileModal.setAttribute('aria-hidden', 'true');
    document.body.style.overflow = '';
  }

  function openMobileModal() {
    if (!mobileModal) {
      return;
    }
    mobileModal.classList.remove('hidden');
    mobileModal.setAttribute('aria-hidden', 'false');
    document.body.style.overflow = 'hidden';
  }

  function handleChoose(mode, tariff, office) {
    if (mode !== 'office' || !office) {
      return;
    }
    syncHiddenFields(office, tariff);
    renderSummary(office);
    if (!desktopMedia.matches) {
      closeMobileModal();
    }
  }

  function createWidget(rootId) {
    return new window.CDEKWidget({
      root: rootId,
      apiKey: config.apiKey,
      servicePath: config.servicePath,
      defaultLocation: config.defaultLocation,
      canChoose: true,
      lang: config.lang || 'rus',
      currency: config.currency || 'RUB',
      hideFilters: config.hideFilters || {},
      hideDeliveryOptions: config.hideDeliveryOptions || {},
      forceFilters: config.forceFilters || {},
      onChoose: handleChoose,
    });
  }

  function initDesktopWidget() {
    if (!state.desktopWidget) {
      state.desktopWidget = createWidget(inlineRootId);
    }
    state.initializedMode = 'desktop';
  }

  function initMobileWidget() {
    if (!state.mobileWidget) {
      state.mobileWidget = createWidget(mobileRootId);
    }
    state.initializedMode = 'mobile';
  }

  function initCurrentMode() {
    if (desktopMedia.matches) {
      initDesktopWidget();
    } else {
      state.initializedMode = 'mobile';
    }
  }

  if (openMobileButton) {
    openMobileButton.addEventListener('click', function () {
      initMobileWidget();
      openMobileModal();
    });
  }

  if (closeMobileButton) {
    closeMobileButton.addEventListener('click', closeMobileModal);
  }

  if (mobileModal) {
    mobileModal.addEventListener('click', function (event) {
      if (event.target === mobileModal) {
        closeMobileModal();
      }
    });
  }

  if (changeButton) {
    changeButton.addEventListener('click', function () {
      if (desktopMedia.matches) {
        if (!state.desktopWidget) {
          initDesktopWidget();
        }
        return;
      }
      initMobileWidget();
      openMobileModal();
    });
  }

  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape') {
      closeMobileModal();
    }
  });

  renderSummary(parseSnapshot(officeRawInput ? officeRawInput.value : ''));
  initCurrentMode();
  if (typeof window.initLucide === 'function') {
    window.initLucide();
  }
})();
