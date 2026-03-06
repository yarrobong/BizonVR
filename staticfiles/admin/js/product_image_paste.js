/**
 * Paste-to-upload for ProductImage inline in Django admin.
 * Press Ctrl+V (Cmd+V on Mac) to paste an image from clipboard into a new row.
 */
(function() {
    'use strict';

    function textContent(node) {
        return node ? node.textContent.replace(/\s+/g, ' ').trim() : '';
    }

    function closest(node, selector) {
        if (!node) return null;
        if (node.closest) return node.closest(selector);
        while (node) {
            if (node.matches && node.matches(selector)) return node;
            node = node.parentNode;
        }
        return null;
    }

    function isEditableTarget(node) {
        return !!closest(
            node,
            'textarea, input:not([type="file"]):not([type="checkbox"]):not([type="radio"]), [contenteditable=""], [contenteditable="true"], [contenteditable="plaintext-only"]'
        );
    }

    function findProductImageInline() {
        var groups = document.querySelectorAll('.inline-group');
        for (var i = 0; i < groups.length; i++) {
            var h2 = groups[i].querySelector('h2');
            var heading = textContent(h2);
            if (heading.indexOf('Фото товара') !== -1 || heading.indexOf('Product image') !== -1) {
                return groups[i];
            }
        }
        return null;
    }

    function getTableBody(group) {
        return group ? group.querySelector('table tbody') : null;
    }

    function getInlineRows(table) {
        if (!table) return [];
        return Array.prototype.filter.call(table.querySelectorAll('tr'), function(row) {
            return !row.classList.contains('empty-form') && !row.classList.contains('add-row');
        });
    }

    function isDeletedRow(row) {
        var deleteInput = row.querySelector('input[name$="-DELETE"]');
        return !!(deleteInput && deleteInput.checked);
    }

    function rowHasPreview(row) {
        return !!row.querySelector('.field-image_preview img');
    }

    function rowHasSelectedFile(row) {
        var fileInput = row.querySelector('input[type="file"]');
        return !!(fileInput && ((fileInput.files && fileInput.files.length) || fileInput.value));
    }

    function findAvailableFileInput(table) {
        var rows = getInlineRows(table);

        for (var i = 0; i < rows.length; i++) {
            if (isDeletedRow(rows[i]) || rowHasPreview(rows[i]) || rowHasSelectedFile(rows[i])) {
                continue;
            }

            var fileInput = rows[i].querySelector('input[type="file"]');
            if (fileInput) {
                return fileInput;
            }
        }

        return null;
    }

    function setFileInput(fileInput, file) {
        if (!fileInput || !file) return;

        try {
            var dt = new DataTransfer();
            dt.items.add(file);
            fileInput.files = dt.files;
            fileInput.dispatchEvent(new Event('change', { bubbles: true }));
        } catch (e) {
            console.warn('Product image paste: could not set file', e);
        }
    }

    function addRowAndSetFile(file) {
        var group = findProductImageInline();
        var table = getTableBody(group);
        var fileInput;
        var addLink;
        var rowCountBefore;

        if (!group || !table) return;

        fileInput = findAvailableFileInput(table);
        if (fileInput) {
            setFileInput(fileInput, file);
            return;
        }

        addLink = group.querySelector('.add-row a, a.add-row');
        if (!addLink) return;

        rowCountBefore = getInlineRows(table).length;
        addLink.click();

        window.requestAnimationFrame(function() {
            window.requestAnimationFrame(function() {
                var rows = getInlineRows(table);
                var newRow = rows[rows.length - 1];

                if (rows.length <= rowCountBefore || !newRow) return;
                setFileInput(newRow.querySelector('input[type="file"]'), file);
            });
        });
    }

    document.addEventListener('paste', function(e) {
        var items = e.clipboardData && e.clipboardData.items;
        if (!items) return;
        if (isEditableTarget(e.target)) return;

        for (var i = 0; i < items.length; i++) {
            if (items[i].type && items[i].type.indexOf('image') !== -1) {
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
