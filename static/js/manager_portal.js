(function () {
  const FILTER_DEBOUNCE_MS = 260;
  const GLOBAL_SEARCH_DEBOUNCE_MS = 180;
  let filterTimers = new WeakMap();
  let globalSearchState = null;

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
    if (!globalSearchState) {
      return;
    }
    globalSearchState.input.focus();
    globalSearchState.input.select();
    requestGlobalSearch(globalSearchState, globalSearchState.input.value.trim());
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
    const form = root.querySelector('[data-manager-global-search]');
    if (!form || form.dataset.managerBound === '1') {
      return;
    }
    const input = form.querySelector('[data-manager-global-search-input]');
    const panel = root.querySelector('[data-manager-global-search-panel]');
    const backdrop = document.querySelector('[data-manager-global-search-backdrop]');
    if (!input || !panel) {
      return;
    }
    form.dataset.managerBound = '1';
    const state = {
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
      }
    });

    form.addEventListener('submit', (event) => {
      event.preventDefault();
      globalSearchState = state;
      submitGlobalSearch(state);
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
  }

  function updateManualOrderSummary(form) {
    let goodsTotal = 0;
    let discountTotal = 0;
    let purchaseTotal = 0;
    let tradeInTotal = 0;

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

    form.querySelectorAll('[data-tradein-item-row]').forEach((row) => {
      if (row.hidden) {
        return;
      }
      const finalEstimate = parseMoney(row.querySelector('[name$="-final_estimate"]')?.value);
      const preliminaryEstimate = parseMoney(row.querySelector('[name$="-preliminary_estimate"]')?.value);
      tradeInTotal += finalEstimate > 0 ? finalEstimate : preliminaryEstimate;
    });

    const deliveryCost = parseMoney(form.querySelector('[name="delivery_cost"]')?.value);
    const avitoCommission = parseMoney(form.querySelector('[name="avito_commission"]')?.value);
    const paidAmount = parseMoney(form.querySelector('[name="prepayment_amount"]')?.value);
    const grandTotal = Math.max(goodsTotal - discountTotal - tradeInTotal, 0) + deliveryCost;
    const balanceDue = grandTotal - paidAmount;
    const expectedMargin = Math.max(goodsTotal - discountTotal - purchaseTotal - avitoCommission - tradeInTotal, 0);
    const balanceLabel = form.querySelector('[data-balance-label]');
    if (balanceLabel) {
      balanceLabel.textContent = balanceDue < 0 ? 'Переплата клиенту' : 'Остаток / доплата';
    }

    const summaryFields = {
      goods_total: goodsTotal,
      delivery_cost: deliveryCost,
      discount_total: discountTotal,
      tradein_total: tradeInTotal,
      avito_commission: avitoCommission,
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
        form.addEventListener('input', () => updateManualOrderSummary(form));
        form.addEventListener('change', () => {
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

      updateDealStatusOptions(form);
      updateManualOrderVisibility(form);
      updateManualOrderSummary(form);
      renumberItemRows(form);
      renumberTradeInRows(form);
    });
  }

  function wireExpandableRows(root) {
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
        if (event.target.closest('a, button, input, select, textarea, label')) {
          return;
        }
        const rowKey = row.dataset.rowToggleRow;
        const button = row.querySelector(`[data-row-toggle="${rowKey}"]`) || root.querySelector(`[data-row-toggle="${rowKey}"]`);
        toggleRow(rowKey, button);
      });
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
    const controlsScope = root.matches?.('[data-manager-deal-board]') ? document : root;
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
        const step = Math.max(Math.round(viewport.clientWidth * 0.92), 280);
        viewport.scrollBy({left: direction * step, behavior: 'smooth'});
      });
    });

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
    wireAutoFilters(root);
    wireBulkSelection(root);
    wireDrawers(root);
    wireRemoteDrawer(root);
    wireMessages(root);
    wireMobileSidebar(root);
    wireManualOrderInteractions(root);
    wireExpandableRows(root);
    wireDealBoard(root);
    wireTabs(root);
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
      closeDrawers();
    }
  });

  window.addEventListener('hashchange', syncTabsWithHash);
  window.addEventListener('popstate', () => {
    syncTabsWithSearch();
    syncTabsWithHash();
  });

  document.addEventListener('DOMContentLoaded', () => {
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
