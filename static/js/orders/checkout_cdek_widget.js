(function () {
  const LEAFLET_CSS_ID = 'leaflet-runtime-css';
  const LEAFLET_SCRIPT_ID = 'leaflet-runtime-js';
  let leafletAssetsPromise = null;

  function ensureLeafletAssets() {
    if (typeof window.L !== 'undefined') {
      return Promise.resolve();
    }
    if (leafletAssetsPromise) {
      return leafletAssetsPromise;
    }

    leafletAssetsPromise = new Promise(function (resolve, reject) {
      if (!document.getElementById(LEAFLET_CSS_ID)) {
        const link = document.createElement('link');
        link.id = LEAFLET_CSS_ID;
        link.rel = 'stylesheet';
        link.href = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css';
        document.head.appendChild(link);
      }

      const existingScript = document.getElementById(LEAFLET_SCRIPT_ID);
      if (existingScript) {
        existingScript.addEventListener('load', function () { resolve(); }, { once: true });
        existingScript.addEventListener('error', function () { reject(new Error('Leaflet failed to load')); }, { once: true });
        return;
      }

      const script = document.createElement('script');
      script.id = LEAFLET_SCRIPT_ID;
      script.src = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js';
      script.async = true;
      script.onload = function () { resolve(); };
      script.onerror = function () { reject(new Error('Leaflet failed to load')); };
      document.head.appendChild(script);
    });

    return leafletAssetsPromise;
  }

  async function initCheckoutCdekWidget() {
    const configNode = document.getElementById('cdek-widget-config');
    const checkoutForm = document.getElementById('checkout-form');
    if (!configNode || !checkoutForm || configNode.dataset.cdekWidgetInitialized === '1') {
      return;
    }

    let config = {};
    try {
      config = JSON.parse(configNode.textContent || '{}');
    } catch (error) {
      window.console.error('Failed to parse CDEK widget config', error);
      return;
    }

    if (!config.enabled) {
      return;
    }

    try {
      await ensureLeafletAssets();
    } catch (error) {
      window.console.error('Failed to load Leaflet assets', error);
      return;
    }

    if (typeof window.L === 'undefined') {
      return;
    }

    configNode.dataset.cdekWidgetInitialized = '1';

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
    const citySearchInput = document.getElementById('cdek-city-search-input');
    const citySearchSubmit = document.getElementById('cdek-city-search-submit');
    const cityResults = document.getElementById('cdek-city-results');
    const officeList = document.getElementById('cdek-office-list');
    const officeCount = document.getElementById('cdek-office-count');
    const officeCaption = document.getElementById('cdek-office-caption');
    const mapLoading = document.getElementById('cdek-map-loading');
    const mapError = document.getElementById('cdek-map-error');
    const mapRoot = document.getElementById('cdek-osm-map');

    const state = {
      map: null,
      markersLayer: null,
      markerByCode: {},
      lastTrigger: null,
      offices: [],
      selectedOfficeCode: '',
      hasAutoLoaded: false,
      pendingRequestId: 0,
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
      summary.dataset.hasSelection = '0';
      return;
    }
    summary.classList.remove('hidden');
    emptyState.classList.add('hidden');
    summary.dataset.hasSelection = '1';
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
    window.requestAnimationFrame(function () {
      initMap();
      if (state.map) {
        state.map.invalidateSize();
      }
      if (!state.hasAutoLoaded) {
        state.hasAutoLoaded = true;
        autoLoadInitialCity();
      }
    });
  }

  function showLoading(message) {
    if (!mapLoading) {
      return;
    }
    mapLoading.textContent = message || 'Загружаем данные CDEK…';
    mapLoading.classList.remove('hidden');
  }

  function hideLoading() {
    if (mapLoading) {
      mapLoading.classList.add('hidden');
    }
  }

  function showError(message) {
    if (!mapError) {
      return;
    }
    if (message) {
      mapError.textContent = message;
      mapError.classList.remove('hidden');
    } else {
      mapError.textContent = '';
      mapError.classList.add('hidden');
    }
  }

  function escapeHtml(value) {
    return String(value || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function toLeafletCoords(rawLocation) {
    if (!Array.isArray(rawLocation) || rawLocation.length < 2) {
      return null;
    }
    const lng = Number(rawLocation[0]);
    const lat = Number(rawLocation[1]);
    if (!Number.isFinite(lat) || !Number.isFinite(lng)) {
      return null;
    }
    return [lat, lng];
  }

  function normalizeOffice(rawOffice) {
    const rawLocation = rawOffice && typeof rawOffice === 'object' ? rawOffice.location : null;
    const lng =
      Array.isArray(rawLocation) && rawLocation.length >= 2
        ? Number(rawLocation[0])
        : Number(rawLocation && (rawLocation.longitude || rawLocation.lng || rawLocation.lon));
    const lat =
      Array.isArray(rawLocation) && rawLocation.length >= 2
        ? Number(rawLocation[1])
        : Number(rawLocation && (rawLocation.latitude || rawLocation.lat));
    const city = (
      rawOffice.city ||
      (rawLocation && rawLocation.city) ||
      (rawLocation && rawLocation.city_name) ||
      ''
    ).toString().trim();
    const address = (
      rawOffice.address ||
      (rawLocation && (rawLocation.address || rawLocation.address_full)) ||
      ''
    ).toString().trim();

    return {
      city_code: rawOffice.city_code || (rawLocation && rawLocation.city_code) || null,
      city: city,
      type: (rawOffice.type || 'PVZ').toString(),
      postal_code: (rawOffice.postal_code || (rawLocation && rawLocation.postal_code) || '').toString(),
      country_code: (rawOffice.country_code || (rawLocation && rawLocation.country_code) || '').toString(),
      have_cashless: Boolean(rawOffice.have_cashless),
      have_cash: Boolean(rawOffice.have_cash),
      allowed_cod: rawOffice.allowed_cod !== false,
      is_dressing_room: Boolean(rawOffice.is_dressing_room),
      code: (rawOffice.code || '').toString().trim(),
      name: (rawOffice.name || rawOffice.code || 'ПВЗ CDEK').toString().trim(),
      address: address,
      work_time: (rawOffice.work_time || '').toString().trim(),
      location: Number.isFinite(lat) && Number.isFinite(lng) ? [lng, lat] : [],
    };
  }

  function normalizeCity(rawCity) {
    const name = (
      rawCity.city ||
      rawCity.name ||
      rawCity.city_name ||
      ''
    ).toString().trim();
    const region = (
      rawCity.region ||
      rawCity.sub_region ||
      rawCity.region_code ||
      ''
    ).toString().trim();
    const country = (
      rawCity.country ||
      rawCity.country_code ||
      ''
    ).toString().trim();

    return {
      code: rawCity.code || rawCity.city_code || null,
      name: name,
      region: region,
      country: country,
      label: [name, region, country].filter(Boolean).join(', '),
    };
  }

  function buildUrl(params) {
    const url = new URL(config.servicePath, window.location.origin);
    Object.keys(params || {}).forEach(function (key) {
      const value = params[key];
      if (value !== null && value !== undefined && value !== '') {
        url.searchParams.set(key, value);
      }
    });
    return url.toString();
  }

  async function requestJson(params) {
    const response = await window.fetch(buildUrl(params), {
      method: 'GET',
      headers: {
        Accept: 'application/json',
      },
      credentials: 'same-origin',
    });
    let payload = null;
    try {
      payload = await response.json();
    } catch (error) {
      payload = null;
    }
    if (!response.ok) {
      const message = payload && payload.message ? payload.message : 'Не удалось получить данные CDEK.';
      throw new Error(message);
    }
    return payload;
  }

  function initialLeafletCenter() {
    const coords = toLeafletCoords(config.defaultLocation);
    return coords || [56.838011, 60.597465];
  }

  function buildMarkerPopup(office) {
    return (
      '<div style="min-width:210px;font-family:inherit">' +
        '<div style="font-weight:700;font-size:13px;margin-bottom:3px;color:#111">' + escapeHtml(office.name) + '</div>' +
        '<div style="font-size:11px;color:#888;margin-bottom:6px">' + escapeHtml(office.code || '') + '</div>' +
        '<div style="font-size:12px;margin-bottom:3px;color:#222">' + escapeHtml(office.address || '') + '</div>' +
        (office.work_time
          ? '<div style="font-size:11px;color:#666;margin-bottom:10px">Часы: ' + escapeHtml(office.work_time) + '</div>'
          : '<div style="margin-bottom:10px"></div>') +
        '<button type="button" data-cdek-popup-select="' + escapeHtml(office.code) + '" ' +
          'style="background:#00D4FF;color:#0B0D14;border:none;border-radius:99px;padding:7px 0;font-size:12px;font-weight:700;cursor:pointer;width:100%;letter-spacing:0.05em">' +
          'Выбрать этот ПВЗ' +
        '</button>' +
      '</div>'
    );
  }

  function initMap() {
    if (!mapRoot || state.map) {
      return;
    }
    state.map = window.L.map(mapRoot, {
      zoomControl: true,
      scrollWheelZoom: true,
    }).setView(initialLeafletCenter(), 11);

    window.L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '&copy; OpenStreetMap contributors',
    }).addTo(state.map);

    state.markersLayer = window.L.layerGroup().addTo(state.map);

    state.map.on('popupopen', function (e) {
      const popup = e.popup;
      const el = popup && popup.getElement();
      const btn = el && el.querySelector('[data-cdek-popup-select]');
      if (!btn) { return; }
      const code = btn.dataset.cdekPopupSelect;
      // Scroll corresponding card into view in the list
      const card = officeList ? officeList.querySelector('[data-cdek-office-card="' + code + '"]') : null;
      if (card) { card.scrollIntoView({ block: 'nearest', behavior: 'smooth' }); }
      btn.addEventListener('click', function () {
        const office = state.offices.find(function (o) { return o.code === code; });
        if (office) { selectOffice(office); }
      }, { once: true });
    });
  }

  function updateMarkerStyles() {
    Object.keys(state.markerByCode).forEach(function (code) {
      const marker = state.markerByCode[code];
      const isSelected = code === state.selectedOfficeCode;
      marker.setStyle({
        radius: isSelected ? 9 : 7,
        color: isSelected ? '#f8d37f' : '#ffffff',
        weight: isSelected ? 2 : 1,
        fillColor: isSelected ? '#f8d37f' : '#f59e0b',
        fillOpacity: isSelected ? 0.95 : 0.78,
      });
    });
  }

  function setOfficeCaption(message) {
    if (officeCaption) {
      officeCaption.textContent = message;
    }
  }

  function setOfficeCount(count) {
    if (officeCount) {
      officeCount.textContent = String(count || 0) + ' ПВЗ';
    }
  }

  function renderCityResults(cities) {
    if (!cityResults) {
      return;
    }
    if (!cities.length) {
      cityResults.classList.add('hidden');
      cityResults.innerHTML = '';
      return;
    }

    cityResults.classList.remove('hidden');
    cityResults.innerHTML =
      '<p class="mb-2 text-xs uppercase tracking-[0.18em] text-gray-500">Уточните город</p>' +
      '<div class="flex flex-wrap gap-2">' +
      cities
        .map(function (city) {
          return (
            '<button type="button" class="inline-flex items-center rounded-full border border-white/10 bg-white/5 px-3 py-1.5 text-sm text-white transition hover:border-white/20 hover:bg-white/10" data-cdek-city-code="' +
            escapeHtml(city.code) +
            '">' +
            escapeHtml(city.label || city.name) +
            '</button>'
          );
        })
        .join('') +
      '</div>';

    Array.from(cityResults.querySelectorAll('[data-cdek-city-code]')).forEach(function (button) {
      button.addEventListener('click', function () {
        const selectedCity = cities.find(function (city) {
          return String(city.code) === button.dataset.cdekCityCode;
        });
        if (selectedCity) {
          loadOfficesForCity(selectedCity);
        }
      });
    });
  }

  function renderOffices() {
    if (!officeList) {
      return;
    }
    if (!state.offices.length) {
      officeList.innerHTML =
        '<div class="rounded-2xl border border-dashed border-white/10 bg-white/[0.03] p-4 text-sm text-gray-500">' +
        'По выбранному городу ПВЗ не найдены. Попробуйте другой запрос.' +
        '</div>';
      return;
    }

    officeList.innerHTML = state.offices
      .map(function (office) {
        const isSelected = office.code === state.selectedOfficeCode;
        return (
          '<article class="rounded-2xl border p-3.5 transition ' +
          (isSelected
            ? 'border-accent/40 bg-accent/10'
            : 'border-white/10 bg-white/[0.03] hover:border-white/20 hover:bg-white/[0.05]') +
          '" data-cdek-office-card="' +
          escapeHtml(office.code) +
          '">' +
          '<div class="flex items-start justify-between gap-3">' +
          '<div class="min-w-0">' +
          '<div class="flex flex-wrap items-center gap-2">' +
          '<h4 class="text-sm font-semibold text-white">' +
          escapeHtml(office.name) +
          '</h4>' +
          '<span class="rounded-full border border-white/10 bg-dark-900/70 px-2.5 py-0.5 text-[11px] uppercase tracking-[0.14em] text-gray-300">' +
          escapeHtml(office.code || 'без кода') +
          '</span>' +
          '</div>' +
          '<p class="mt-2 text-sm leading-5 text-gray-300">' +
          escapeHtml(office.address || 'Адрес уточним у CDEK') +
          '</p>' +
          '<p class="mt-1 text-xs text-gray-500">' +
          escapeHtml(office.city || 'Город не указан') +
          '</p>' +
          '<p class="mt-2 text-xs text-gray-400">Часы работы: ' +
          escapeHtml(office.work_time || 'Уточним у CDEK') +
          '</p>' +
          '</div>' +
          '<button type="button" class="inline-flex shrink-0 items-center justify-center rounded-full px-4 py-2 text-sm font-medium transition ' +
          (isSelected
            ? 'border border-accent/30 bg-accent text-dark-900'
            : 'border border-white/10 bg-white/5 text-white hover:border-white/20 hover:bg-white/10') +
          '" data-cdek-choose-office="' +
          escapeHtml(office.code) +
          '">' +
          (isSelected ? 'Выбрано' : 'Выбрать') +
          '</button>' +
          '</div>' +
          '</article>'
        );
      })
      .join('');

    Array.from(officeList.querySelectorAll('[data-cdek-choose-office]')).forEach(function (button) {
      button.addEventListener('click', function () {
        const office = state.offices.find(function (item) {
          return item.code === button.dataset.cdekChooseOffice;
        });
        if (office) {
          selectOffice(office);
        }
      });
    });
  }

  function renderMapMarkers() {
    if (!state.markersLayer) {
      return;
    }

    state.markersLayer.clearLayers();
    state.markerByCode = {};
    const bounds = [];

    state.offices.forEach(function (office) {
      const coords = toLeafletCoords(office.location);
      if (!coords) {
        return;
      }
      bounds.push(coords);
      const marker = window.L.circleMarker(coords, {
        radius: 7,
        color: '#ffffff',
        weight: 1,
        fillColor: '#f59e0b',
        fillOpacity: 0.78,
      });
      marker.bindPopup(buildMarkerPopup(office), { maxWidth: 260, minWidth: 210 });
      marker.addTo(state.markersLayer);
      if (office.code) {
        state.markerByCode[office.code] = marker;
      }
    });

    updateMarkerStyles();

    if (!state.map) {
      return;
    }
    if (bounds.length === 1) {
      state.map.setView(bounds[0], 15);
      return;
    }
    if (bounds.length > 1) {
      state.map.fitBounds(bounds, {
        padding: [24, 24],
        maxZoom: 15,
      });
    }
  }

  function highlightSelectedOffice() {
    updateMarkerStyles();
    const selectedCard = officeList
      ? Array.from(officeList.querySelectorAll('[data-cdek-office-card]')).find(function (node) {
          return node.getAttribute('data-cdek-office-card') === state.selectedOfficeCode;
        })
      : null;
    if (selectedCard && typeof selectedCard.scrollIntoView === 'function') {
      selectedCard.scrollIntoView({
        block: 'nearest',
        behavior: 'smooth',
      });
    }
    const marker = state.markerByCode[state.selectedOfficeCode];
    if (marker) {
      marker.openPopup();
      if (state.map) {
        state.map.panTo(marker.getLatLng(), {
          animate: true,
        });
      }
    }
  }

  function selectOffice(office) {
    state.selectedOfficeCode = office.code || '';
    syncHiddenFields(office, null);
    renderSummary(office);
    renderOffices();
    highlightSelectedOffice();
    closeModal();
  }

  async function loadOfficesForCity(city) {
    const requestId = ++state.pendingRequestId;
    showError('');
    showLoading('Загружаем ПВЗ CDEK для города ' + (city.name || '…') + '…');
    setOfficeCaption('Загружаем пункты выдачи для города ' + (city.label || city.name) + '…');
    setOfficeCount(0);
    renderCityResults([city]);

    try {
      const payload = await requestJson({
        action: 'offices',
        city_code: city.code,
        type: 'PVZ',
      });

      if (requestId !== state.pendingRequestId) {
        return;
      }

      state.offices = Array.isArray(payload)
        ? payload.map(normalizeOffice).filter(function (office) {
            return office.code && office.address;
          })
        : [];

      if (citySearchInput) {
        citySearchInput.value = city.name || '';
      }
      if (cityResults) {
        cityResults.classList.add('hidden');
        cityResults.innerHTML = '';
      }

      setOfficeCount(state.offices.length);
      setOfficeCaption(
        state.offices.length
          ? 'Найдено ' + state.offices.length + ' ПВЗ для города ' + (city.name || '') + '.'
          : 'По городу ' + (city.name || '') + ' ПВЗ не найдено.'
      );
      renderOffices();
      renderMapMarkers();

      if (!state.selectedOfficeCode) {
        return;
      }
      if (state.offices.some(function (office) { return office.code === state.selectedOfficeCode; })) {
        renderOffices();
        highlightSelectedOffice();
      }
    } catch (error) {
      if (requestId !== state.pendingRequestId) {
        return;
      }
      state.offices = [];
      setOfficeCount(0);
      setOfficeCaption('Не удалось загрузить пункты выдачи CDEK.');
      renderOffices();
      showError(error.message || 'Не удалось загрузить пункты выдачи CDEK.');
    } finally {
      if (requestId === state.pendingRequestId) {
        hideLoading();
      }
    }
  }

  async function searchCities(query, options) {
    const trimmedQuery = (query || '').trim();
    const searchOptions = options || {};
    if (!trimmedQuery) {
      showError('Введите город, чтобы загрузить пункты выдачи CDEK.');
      return;
    }

    const requestId = ++state.pendingRequestId;
    showError('');
    showLoading('Ищем город в справочнике CDEK…');
    setOfficeCaption('Ищем город "' + trimmedQuery + '"…');
    state.offices = [];
    setOfficeCount(0);
    renderOffices();

    try {
      const payload = await requestJson({
        action: 'cities',
        city: trimmedQuery,
        country_code: 'RU',
        size: 10,
      });

      if (requestId !== state.pendingRequestId) {
        return;
      }

      const cities = Array.isArray(payload)
        ? payload.map(normalizeCity).filter(function (city) {
            return city.code && city.name;
          })
        : [];

      if (!cities.length) {
        renderCityResults([]);
        state.offices = [];
        setOfficeCount(0);
        renderOffices();
        setOfficeCaption('Город не найден в справочнике CDEK. Попробуйте другой вариант.');
        showError('Не нашли город в справочнике CDEK. Уточните название и попробуйте ещё раз.');
        return;
      }

      renderCityResults(cities);
      setOfficeCaption('Выберите точный город из списка.');
      if (searchOptions.autoselectFirst) {
        const preferredCity = cities.find(function (city) {
          return searchOptions.preferredCode && String(city.code) === String(searchOptions.preferredCode);
        });
        loadOfficesForCity(preferredCity || cities[0]);
      }
    } catch (error) {
      if (requestId !== state.pendingRequestId) {
        return;
      }
      renderCityResults([]);
      setOfficeCaption('Не удалось загрузить справочник городов CDEK.');
      showError(error.message || 'Не удалось найти город в CDEK.');
    } finally {
      if (requestId === state.pendingRequestId) {
        hideLoading();
      }
    }
  }

  function autoLoadInitialCity() {
    const currentOffice = parseSnapshot(officeRawInput ? officeRawInput.value : '');
    const initialCity = (config.defaultCity || (currentOffice && currentOffice.city) || '').trim();
    const initialCityCode = config.defaultCityCode || (currentOffice && currentOffice.city_code) || null;

    initMap();
    renderOffices();

    if (citySearchInput && initialCity) {
      citySearchInput.value = initialCity;
    }

    if (initialCityCode && initialCity) {
      loadOfficesForCity({
        code: initialCityCode,
        name: initialCity,
        label: initialCity,
      });
      return;
    }
    if (initialCity) {
      searchCities(initialCity, {
        autoselectFirst: true,
        preferredCode: initialCityCode,
      });
    }
  }

  function triggerCitySearch() {
    const query = citySearchInput ? citySearchInput.value : '';
    searchCities(query, {
      autoselectFirst: false,
    });
  }

    openButtons.forEach(function (button) {
      button.addEventListener('click', function () {
        state.lastTrigger = button;
        openModal();
      });
    });

    closeButtons.forEach(function (button) {
      button.addEventListener('click', closeModal);
    });

    changeButtons.forEach(function (button) {
      button.addEventListener('click', function () {
        state.lastTrigger = button;
        openModal();
      });
    });

    if (citySearchSubmit) {
      citySearchSubmit.addEventListener('click', triggerCitySearch);
    }

    if (citySearchInput) {
      citySearchInput.addEventListener('keydown', function (event) {
        if (event.key === 'Enter') {
          event.preventDefault();
          triggerCitySearch();
        }
      });
    }

    let cityTypeTimer = null;
    if (citySearchInput) {
      citySearchInput.addEventListener('input', function () {
        if (cityTypeTimer) {
          clearTimeout(cityTypeTimer);
        }
        const query = (citySearchInput.value || '').trim();
        if (!query) {
          renderCityResults([]);
          return;
        }
        cityTypeTimer = setTimeout(function () {
          cityTypeTimer = null;
          searchCities(query, { autoselectFirst: false });
        }, 300);
      });
    }

    if (modal) {
      modal.addEventListener('click', function (event) {
        if (event.target === modal) {
          closeModal();
        }
      });
      modal.setAttribute('inert', '');
    }

    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape') {
        closeModal();
      }
    });

    const currentOffice = normalizeOffice(parseSnapshot(officeRawInput ? officeRawInput.value : '') || {});
    if (currentOffice.code) {
      state.selectedOfficeCode = currentOffice.code;
      renderSummary(currentOffice);
    } else {
      renderSummary(null);
    }

    if (typeof window.initLucide === 'function') {
      window.initLucide();
    }
  }

  window.initCheckoutCdekWidget = initCheckoutCdekWidget;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      initCheckoutCdekWidget();
    });
  } else {
    initCheckoutCdekWidget();
  }

  document.body?.addEventListener('htmx:afterSwap', function (event) {
    if (event.detail.target && event.detail.target.id === 'main-content') {
      initCheckoutCdekWidget();
    }
  });
})();
