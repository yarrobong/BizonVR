/**
 * Paste-to-upload for ProductImage inline in Django admin.
 * Press Ctrl+V (Cmd+V on Mac) to paste an image from clipboard into a new row.
 */
(function() {
    'use strict';

    function findProductImageInline() {
        var groups = document.querySelectorAll('.inline-group');
        for (var i = 0; i < groups.length; i++) {
            var h2 = groups[i].querySelector('h2');
            if (h2 && (h2.textContent.indexOf('Фото товара') !== -1 || h2.textContent.indexOf('Product image') !== -1)) {
                return groups[i];
            }
        }
        return null;
    }

    function addRowAndSetFile(file) {
        var group = findProductImageInline();
        if (!group) return;

        var addLink = group.querySelector('a.add-row');
        if (!addLink) return;

        var table = group.querySelector('table tbody');
        if (!table) return;

        var rowCountBefore = table.querySelectorAll('tr').length;
        addLink.click();

        setTimeout(function() {
            var rows = table.querySelectorAll('tr');
            var newRow = rows[rows.length - 1];
            if (rows.length <= rowCountBefore || !newRow) return;

            var fileInput = newRow.querySelector('input[type="file"]');
            if (!fileInput) return;

            try {
                var dt = new DataTransfer();
                dt.items.add(file);
                fileInput.files = dt.files;
                fileInput.dispatchEvent(new Event('change', { bubbles: true }));
            } catch (e) {
                console.warn('Product image paste: could not set file', e);
            }
        }, 50);
    }

    document.addEventListener('paste', function(e) {
        var items = e.clipboardData && e.clipboardData.items;
        if (!items) return;

        for (var i = 0; i < items.length; i++) {
            if (items[i].type.indexOf('image') !== -1) {
                e.preventDefault();
                var file = items[i].getAsFile();
                if (file) {
                    addRowAndSetFile(file);
                }
                return;
            }
        }
    });
})();
