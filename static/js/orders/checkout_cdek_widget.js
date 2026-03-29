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

  const emptyState = document.getElementById('cdek-selection-empty');
  const summary = document.getElementById('cdek-selection-summary');
  const modal = document.getElementById('cdek-widget-modal');
  const openButtons = Array.from(document.querySelectorAll('[data-cdek-open]'));
  const closeButtons = Array.from(document.querySelectorAll('[data-cdek-close]'));
  const changeButtons = Array.from(document.querySelectorAll('[data-cdek-change]'));
  const cityInput = document.getElementById('id_city_text');
  const addressInput = document.getElementById('id_address_line');
  const officeRawInput = document.getElementById('id_cdek_office_snapshot_raw');
  const tariffRawInput = document.getElementById('id_cdek_tariff_snapshot_raw');
  const modalRootId = 'cdek-widget-modal-root';

  const state = {
    widget: null,
    lastTrigger: null,
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
    if (!summary || !emptyState) {
      return;
    }
    if (!office) {
      summary.classList.add('hidden');
      emptyState.classList.remove('hidden');
      return;
    }
    summary.classList.remove('hidden');
    emptyState.classList.add('hidden');
    setSummaryValue('[data-cdek-city]', office.city, 'Не выбран');
    setSummaryValue('[data-cdek-code]', office.code, '—');
    setSummaryValue('[data-cdek-name]', office.name, '—');
    setSummaryValue('[data-cdek-address]', office.address, '—');
    setSummaryValue('[data-cdek-work-time]', office.work_time, 'Уточним у СДЭК');
    setSummaryValue('[data-cdek-code-badge]', office.code ? 'Код ' + office.code : 'Код не выбран', 'Код не выбран');
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

  function closeModal() {
    if (!modal) {
      return;
    }
    const activeElement = document.activeElement;
    if (activeElement && modal.contains(activeElement) && typeof activeElement.blur === 'function') {
      activeElement.blur();
    }
    modal.classList.add('hidden');
    modal.setAttribute('aria-hidden', 'true');
    modal.setAttribute('inert', '');
    document.body.style.overflow = '';
    if (state.lastTrigger && typeof state.lastTrigger.focus === 'function') {
      window.requestAnimationFrame(function () {
        state.lastTrigger.focus();
      });
    }
  }

  function openModal() {
    if (!modal) {
      return;
    }
    modal.classList.remove('hidden');
    modal.setAttribute('aria-hidden', 'false');
    modal.removeAttribute('inert');
    document.body.style.overflow = 'hidden';
  }

  function handleChoose(mode, tariff, office) {
    if (mode !== 'office' || !office) {
      return;
    }
    syncHiddenFields(office, tariff);
    renderSummary(office);
    closeModal();
  }

  function createWidget() {
    return new window.CDEKWidget({
      root: modalRootId,
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

  function initWidget() {
    if (!state.widget) {
      state.widget = createWidget();
    }
  }

  openButtons.forEach(function (button) {
    button.addEventListener('click', function () {
      state.lastTrigger = button;
      openModal();
      window.requestAnimationFrame(initWidget);
    });
  });

  closeButtons.forEach(function (button) {
    button.addEventListener('click', closeModal);
  });

  if (modal) {
    modal.addEventListener('click', function (event) {
      if (event.target === modal) {
        closeModal();
      }
    });
  }

  changeButtons.forEach(function (button) {
    button.addEventListener('click', function () {
      state.lastTrigger = button;
      openModal();
      window.requestAnimationFrame(initWidget);
    });
  });

  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape') {
      closeModal();
    }
  });

  renderSummary(parseSnapshot(officeRawInput ? officeRawInput.value : ''));
  if (modal) {
    modal.setAttribute('inert', '');
  }
  if (typeof window.initLucide === 'function') {
    window.initLucide();
  }
})();
