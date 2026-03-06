(function() {
  window.catalogProductList = function() {
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
})();
