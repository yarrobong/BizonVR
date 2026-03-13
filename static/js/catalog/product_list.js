(function() {
  window.catalogProductList = function() {
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
})();
