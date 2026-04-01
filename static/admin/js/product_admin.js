/**
 * UX helpers for Product admin change form.
 */
(function() {
    'use strict';

    function onReady(fn) {
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', fn);
            return;
        }
        fn();
    }

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

    function isInsideManagedPanel(node) {
        return !!closest(node, '[data-product-admin-summary], [data-product-admin-alerts]');
    }

    function getInlineGroupById(id) {
        return document.getElementById(id);
    }

    function findInlineGroupByHeading(text) {
        var groups = document.querySelectorAll('.inline-group');
        var lowerText = text.toLowerCase();
        var match = null;

        Array.prototype.some.call(groups, function(group) {
            var heading = group.querySelector('h2');
            if (textContent(heading).toLowerCase().indexOf(lowerText) !== -1) {
                match = group;
                return true;
            }
            return false;
        });

        return match;
    }

    function isDeletedRow(row) {
        var deleteInput = row.querySelector('input[name$="-DELETE"]');
        return !!(deleteInput && deleteInput.checked);
    }

    function getInlineRows(group) {
        if (!group) return [];
        var rows = group.querySelectorAll('tbody > tr');
        return Array.prototype.filter.call(rows, function(row) {
            return !row.classList.contains('empty-form') && !row.classList.contains('add-row');
        });
    }

    function rowHasImage(row) {
        var previewImage = row.querySelector('.field-image_preview img');
        var fileInput = row.querySelector('input[type="file"]');
        return !!(previewImage || (fileInput && fileInput.files && fileInput.files.length));
    }

    function rowHasVariant(row) {
        var nameInput = row.querySelector('input[name$="-name"]');
        var priceInput = row.querySelector('input[name$="-price_override"]');
        var orderInput = row.querySelector('input[name$="-order"]');
        return !!(
            rowHasImage(row) ||
            (nameInput && nameInput.value.trim()) ||
            (priceInput && priceInput.value.trim()) ||
            (orderInput && orderInput.value.trim())
        );
    }

    function rowHasStock(row) {
        var pickupInput = row.querySelector('select[name$="-pickup_point"], input[name$="-pickup_point"]');
        var variantInput = row.querySelector('select[name$="-variant"], input[name$="-variant"]');
        var quantityInput = row.querySelector('input[name$="-quantity"]');
        return !!(
            (pickupInput && pickupInput.value) ||
            (variantInput && variantInput.value) ||
            (quantityInput && quantityInput.value.trim() && quantityInput.value.trim() !== '0')
        );
    }

    function countActiveRows(group, detector) {
        return getInlineRows(group).filter(function(row) {
            return !isDeletedRow(row) && detector(row);
        }).length;
    }

    function countRowsWithPriceOverride(group) {
        return getInlineRows(group).filter(function(row) {
            if (isDeletedRow(row)) return false;
            var priceInput = row.querySelector('input[name$="-price_override"]');
            return !!(priceInput && priceInput.value.trim());
        }).length;
    }

    function markPhotoPrimaryRow(group) {
        var rows = getInlineRows(group);
        var firstRow = null;

        rows.forEach(function(row) {
            row.classList.remove('is-primary-image');
        });

        rows.some(function(row) {
            if (!isDeletedRow(row) && rowHasImage(row)) {
                firstRow = row;
                return true;
            }
            return false;
        });

        if (firstRow) {
            firstRow.classList.add('is-primary-image');
        }
    }

    function setCheckState(selector, status, label) {
        var item = document.querySelector(selector);
        var stateNode;

        if (!item) return;

        item.classList.remove('is-complete', 'is-warning', 'is-pending');
        item.classList.add(status);

        stateNode = item.querySelector('strong');
        if (stateNode && label) {
            stateNode.textContent = label;
        }
    }

    function setText(selector, value) {
        var node = document.querySelector(selector);
        if (node) {
            node.textContent = value;
        }
    }

    function setWidth(selector, value) {
        var node = document.querySelector(selector);
        if (node) {
            node.style.width = value;
        }
    }

    function buildScrollOffset() {
        var offset = 24;
        var stickyNav = document.querySelector('[data-product-admin-anchor-nav]');
        var stickySubmit = document.querySelector('.change-form #content-main form > .submit-row:first-of-type');

        if (stickySubmit) offset += stickySubmit.getBoundingClientRect().height;
        if (stickyNav) offset += stickyNav.getBoundingClientRect().height;
        return offset;
    }

    function scrollToTarget(targetKey) {
        var target = null;
        var top;

        if (targetKey === 'field-name') {
            target = closest(document.getElementById('id_name'), '.form-row') || document.getElementById('id_name');
        } else {
            target = getInlineGroupById(targetKey);
        }

        if (!target) {
            if (targetKey === 'inline-description-group') target = descriptionFieldset || findInlineGroupByHeading('Характеристики');
            if (targetKey === 'inline-images-group') target = findInlineGroupByHeading('Фото товара');
            if (targetKey === 'inline-variants-group') target = findInlineGroupByHeading('Варианты товара');
            if (targetKey === 'inline-stocks-group') target = findInlineGroupByHeading('Остатки');
            if (targetKey === 'inline-bundle_items-group') target = findInlineGroupByHeading('комплект');
        }

        if (!target) return;

        top = target.getBoundingClientRect().top + window.pageYOffset - buildScrollOffset();
        window.scrollTo({ top: Math.max(top, 0), behavior: 'smooth' });
    }

    function getRowFilePreview(row) {
        var fileInput = row ? row.querySelector('input[type="file"]') : null;
        if (!fileInput || !fileInput.files || !fileInput.files.length || !window.URL || !window.URL.createObjectURL) {
            return '';
        }
        return window.URL.createObjectURL(fileInput.files[0]);
    }

    function ensureLockMessage(group, title, description) {
        var lockMessage;

        if (!group) return;
        lockMessage = group.querySelector('.product-inline-group__lock');
        if (lockMessage) return;

        lockMessage = document.createElement('div');
        lockMessage.className = 'product-inline-group__lock';
        lockMessage.innerHTML = '<strong>' + title + '</strong><p>' + description + '</p>';
        group.appendChild(lockMessage);
    }

    function ensureFieldNote(field, dataKey) {
        var row = closest(field, '.form-row');
        var existing = row ? row.querySelector('[' + dataKey + ']') : null;
        var note;

        if (!row) return null;
        if (existing) return existing;

        note = document.createElement('div');
        note.className = 'product-admin-field-note';
        note.setAttribute(dataKey, 'true');
        field.parentNode.appendChild(note);
        return note;
    }

    function ensureSkuMirrorInput(skuInput) {
        var mirror = document.querySelector('input[data-product-admin-sku-mirror]');
        if (!mirror) {
            mirror = document.createElement('input');
            mirror.type = 'hidden';
            mirror.name = skuInput.name;
            mirror.setAttribute('data-product-admin-sku-mirror', 'true');
            skuInput.parentNode.appendChild(mirror);
        }
        mirror.value = skuInput.value;
        return mirror;
    }

    function removeSkuMirrorInput() {
        var mirror = document.querySelector('input[data-product-admin-sku-mirror]');
        if (mirror && mirror.parentNode) {
            mirror.parentNode.removeChild(mirror);
        }
    }

    function updateSkuFieldState(skuInput, variantCount) {
        var row;
        if (!skuInput) return;
        row = closest(skuInput, '.form-row');
        if (!row) return;
        row.hidden = variantCount > 0;
    }

    function ensureDescriptionMeta(descriptionInput) {
        var existing = descriptionInput.parentNode.querySelector('[data-product-admin-description-meta]');
        var meta;
        var count;
        var hint;

        if (existing) {
            return {
                meta: existing,
                count: existing.querySelector('[data-product-admin-description-count]'),
                hint: existing.querySelector('[data-product-admin-description-hint]')
            };
        }

        meta = document.createElement('div');
        meta.className = 'product-admin-description-meta';
        meta.setAttribute('data-product-admin-description-meta', 'true');

        count = document.createElement('span');
        count.className = 'product-admin-description-meta__count';
        count.setAttribute('data-product-admin-description-count', 'true');

        hint = document.createElement('span');
        hint.className = 'product-admin-description-meta__hint';
        hint.setAttribute('data-product-admin-description-hint', 'true');

        meta.appendChild(count);
        meta.appendChild(hint);
        descriptionInput.parentNode.appendChild(meta);

        return { meta: meta, count: count, hint: hint };
    }

    function updateDescriptionMeta(descriptionInput) {
        var parts;
        var normalizedLength;
        var softMin;
        var softMax;

        if (!descriptionInput) return;

        parts = ensureDescriptionMeta(descriptionInput);
        normalizedLength = descriptionInput.value.replace(/\s+/g, ' ').trim().length;
        softMin = parseInt(descriptionInput.getAttribute('data-soft-min-length') || '300', 10);
        softMax = parseInt(descriptionInput.getAttribute('data-soft-max-length') || '1200', 10);

        parts.meta.classList.remove('is-short', 'is-good', 'is-long');
        parts.count.textContent = String(normalizedLength) + ' символов';

        if (!normalizedLength) {
            parts.meta.classList.add('is-short');
            parts.hint.textContent = 'Описание пока пустое. Рекомендуем минимум ' + String(softMin) + ' символов.';
            return;
        }

        if (normalizedLength < softMin) {
            parts.meta.classList.add('is-short');
            parts.hint.textContent = 'Коротко для витрины. Добавьте преимущества, комплектацию и сценарий использования.';
            return;
        }

        if (normalizedLength <= softMax) {
            parts.meta.classList.add('is-good');
            parts.hint.textContent = 'Хороший объём для карточки. Текст уже выглядит достаточно информативным.';
            return;
        }

        parts.meta.classList.add('is-long');
        parts.hint.textContent = 'Описание длиннее рекомендации. Проверьте, не прячутся ли ключевые преимущества слишком глубоко.';
    }

    function ensureImageLightbox() {
        var existing = document.querySelector('[data-product-admin-image-lightbox]');
        var overlay;
        var dialog;
        var actions;
        var closeButton;
        var openButton;
        var canvas;
        var image;

        if (existing) {
            return {
                overlay: existing,
                image: existing.querySelector('[data-product-admin-image-lightbox-image]'),
                openButton: existing.querySelector('[data-product-admin-image-lightbox-open]'),
            };
        }

        overlay = document.createElement('div');
        overlay.className = 'product-admin-image-lightbox';
        overlay.hidden = true;
        overlay.setAttribute('data-product-admin-image-lightbox', 'true');

        dialog = document.createElement('div');
        dialog.className = 'product-admin-image-lightbox__dialog';

        actions = document.createElement('div');
        actions.className = 'product-admin-image-lightbox__actions';

        openButton = document.createElement('a');
        openButton.className = 'button product-admin-image-lightbox__button';
        openButton.target = '_blank';
        openButton.rel = 'noreferrer';
        openButton.textContent = 'Открыть в новой вкладке';
        openButton.setAttribute('data-product-admin-image-lightbox-open', 'true');

        closeButton = document.createElement('button');
        closeButton.type = 'button';
        closeButton.className = 'button product-admin-image-lightbox__button';
        closeButton.textContent = 'Закрыть';
        closeButton.setAttribute('data-product-admin-image-lightbox-close', 'true');

        canvas = document.createElement('div');
        canvas.className = 'product-admin-image-lightbox__canvas';

        image = document.createElement('img');
        image.alt = '';
        image.setAttribute('data-product-admin-image-lightbox-image', 'true');

        canvas.appendChild(image);
        actions.appendChild(openButton);
        actions.appendChild(closeButton);
        dialog.appendChild(actions);
        dialog.appendChild(canvas);
        overlay.appendChild(dialog);
        document.body.appendChild(overlay);

        return {
            overlay: overlay,
            image: image,
            openButton: openButton,
        };
    }

    function setupImagePreviewLightbox() {
        var parts = ensureImageLightbox();

        function closeLightbox() {
            parts.overlay.hidden = true;
            parts.image.removeAttribute('src');
            parts.openButton.removeAttribute('href');
        }

        document.addEventListener('click', function(event) {
            var previewLink = closest(event.target, '[data-product-admin-image-preview-link]');
            var closeButton = closest(event.target, '[data-product-admin-image-lightbox-close]');
            var dialog = closest(event.target, '.product-admin-image-lightbox__dialog');

            if (closeButton) {
                closeLightbox();
                return;
            }

            if (previewLink) {
                if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
                event.preventDefault();
                parts.image.src = previewLink.getAttribute('href');
                parts.openButton.href = previewLink.getAttribute('href');
                parts.overlay.hidden = false;
                return;
            }

            if (!parts.overlay.hidden && event.target === parts.overlay && !dialog) {
                closeLightbox();
            }
        });

        document.addEventListener('keydown', function(event) {
            if (event.key === 'Escape' && !parts.overlay.hidden) {
                closeLightbox();
            }
        });
    }

    function setupTagsWidget() {
        var firstTagCheckbox = document.querySelector('input[data-product-admin-tags-widget]');
        var tagsRoot = firstTagCheckbox
            ? (firstTagCheckbox.parentElement && firstTagCheckbox.parentElement.parentElement && firstTagCheckbox.parentElement.parentElement.parentElement)
            : null;
        var fieldRow;
        var shell;
        var toolbar;
        var searchInput;
        var countNode;
        var emptyNode;
        var items;

        function refresh() {
            var query;
            var visibleCount = 0;

            if (!items.length) return;

            query = searchInput.value.replace(/\s+/g, ' ').trim().toLowerCase();
            items.forEach(function(item) {
                var text = item.label.textContent.replace(/\s+/g, ' ').trim().toLowerCase();
                var matches = !query || text.indexOf(query) !== -1;
                item.wrapper.hidden = !matches;
                if (matches) visibleCount += 1;
            });

            countNode.textContent = query
                ? 'Найдено тегов: ' + String(visibleCount)
                : 'Всего тегов: ' + String(items.length);
            emptyNode.hidden = visibleCount !== 0;
        }

        if (!tagsRoot || tagsRoot.getAttribute('data-tags-enhanced') === 'true') return;

        fieldRow = closest(tagsRoot, '.form-row');
        if (!fieldRow) return;

        items = Array.prototype.map.call(
            tagsRoot.querySelectorAll('input[type="checkbox"]'),
            function(checkbox) {
                var label = closest(checkbox, 'label');
                var wrapper = label && label.parentElement ? label.parentElement : checkbox.parentElement;
                return {
                    checkbox: checkbox,
                    label: label,
                    wrapper: wrapper
                };
            }
        ).filter(function(item) {
            return item.label && item.wrapper;
        });

        if (!items.length) return;

        shell = document.createElement('div');
        shell.setAttribute('data-product-admin-tags-shell', 'true');

        toolbar = document.createElement('div');
        toolbar.setAttribute('data-product-admin-tags-toolbar', 'true');

        searchInput = document.createElement('input');
        searchInput.type = 'search';
        searchInput.placeholder = 'Поиск по тегам';
        searchInput.className = 'vTextField';
        searchInput.setAttribute('data-product-admin-tags-search', 'true');

        countNode = document.createElement('span');
        countNode.setAttribute('data-product-admin-tags-count', 'true');

        emptyNode = document.createElement('p');
        emptyNode.setAttribute('data-product-admin-tags-empty', 'true');
        emptyNode.textContent = 'По вашему запросу теги не найдены.';
        emptyNode.hidden = true;

        toolbar.appendChild(searchInput);
        toolbar.appendChild(countNode);

        tagsRoot.parentNode.insertBefore(shell, tagsRoot);
        shell.appendChild(toolbar);
        shell.appendChild(tagsRoot);
        shell.appendChild(emptyNode);
        tagsRoot.setAttribute('data-tags-enhanced', 'true');

        searchInput.addEventListener('input', refresh);
        refresh();
    }

    function getStackedInlineRows(group) {
        if (!group) return [];
        return Array.prototype.filter.call(group.querySelectorAll('.inline-related'), function(row) {
            return !row.classList.contains('empty-form');
        });
    }

    function getFieldRow(container, fieldName) {
        return container ? container.querySelector('.form-row.field-' + fieldName) : null;
    }

    function setFieldVisibility(container, fieldName, visible) {
        var row = getFieldRow(container, fieldName);
        if (!row) return;
        row.classList.toggle('is-hidden-by-block-type', !visible);
        row.setAttribute('aria-hidden', visible ? 'false' : 'true');
    }

    function applyContentBlockFieldVisibility(group) {
        var rows;
        var visibilityMap;

        if (!group) return;

        visibilityMap = {
            text: {
                title: true,
                text: true,
                image_preview: false,
                image: false,
                rutube_preview: false,
                rutube_url: false,
                image_position: false,
                caption: false,
                sort_order: true,
                is_active: true
            },
            image_text: {
                title: true,
                text: true,
                image_preview: true,
                image: true,
                rutube_preview: false,
                rutube_url: false,
                image_position: true,
                caption: false,
                sort_order: true,
                is_active: true
            },
            full_image: {
                title: true,
                text: false,
                image_preview: true,
                image: true,
                rutube_preview: false,
                rutube_url: false,
                image_position: false,
                caption: true,
                sort_order: true,
                is_active: true
            },
            video: {
                title: true,
                text: false,
                image_preview: false,
                image: false,
                rutube_preview: true,
                rutube_url: true,
                image_position: false,
                caption: true,
                sort_order: true,
                is_active: true
            }
        };

        rows = getStackedInlineRows(group);
        rows.forEach(function(row) {
            var typeField = row.querySelector('select[name$="-block_type"]');
            var currentType = typeField && typeField.value ? typeField.value : 'text';
            var currentMap = visibilityMap[currentType] || visibilityMap.text;

            row.classList.add('product-content-block-inline');
            row.setAttribute('data-block-type', currentType);

            Object.keys(visibilityMap.text).forEach(function(fieldName) {
                setFieldVisibility(row, fieldName, !!currentMap[fieldName]);
            });
        });
    }

    function escapeHtml(s) {
        return String(s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function blockTypeLabel(type) {
        var map = { text: 'Текст', image_text: 'Изображение + текст', full_image: 'Изображение', video: 'Видео' };
        return map[type] || type;
    }

    onReady(function() {
        // Auto-collapse sidebar on product admin pages; remember user's explicit choice.
        // setTimeout(0) defers until after nav_sidebar.js has created the toggle button.
        // Django admin puts the 'shifted' class on #main (not #container).
        setTimeout(function() {
            var PREF_KEY = 'product_admin.sidebarOpen';
            var main = document.getElementById('main');
            var toggle = document.getElementById('toggle-nav-sidebar');
            var autoCollapsing = false;

            if (!main || !toggle) return;

            toggle.addEventListener('click', function() {
                if (autoCollapsing) return;
                window.requestAnimationFrame(function() {
                    if (main.classList.contains('shifted')) {
                        localStorage.setItem(PREF_KEY, '1');
                    } else {
                        localStorage.removeItem(PREF_KEY);
                    }
                });
            });

            if (localStorage.getItem(PREF_KEY) !== '1' && main.classList.contains('shifted')) {
                autoCollapsing = true;
                toggle.click();
                autoCollapsing = false;
            }
        }, 0);

        var dashboard = document.querySelector('[data-product-admin-dashboard]');
        var refreshScheduled = false;
        var mode;
        var nameInput;
        var categoryInput;
        var priceInput;
        var skuInput;
        var descriptionInput;
        var optionLabelInput;
        var slugInput;
        var alertsBox;
        var alertsList;
        var photoGroup;
        var videoGroup;
        var contentBlockGroup;
        var variantGroup;
        var characteristicsGroup;
        var stockGroup;
        var bundleGroup;
        var descriptionFieldset;
        var previewImageNode;
        var previewPlaceholderNode;
        var currentPreviewObjectUrl = '';

        if (!dashboard) return;

        mode = dashboard.getAttribute('data-mode');
        nameInput = document.getElementById('id_name');
        categoryInput = document.getElementById('id_category');
        priceInput = document.getElementById('id_price');
        skuInput = document.getElementById('id_sku');
        descriptionInput = document.getElementById('id_description');
        optionLabelInput = document.getElementById('id_option_label');
        slugInput = document.getElementById('id_slug');
        alertsBox = document.querySelector('[data-product-admin-alerts]');
        alertsList = document.querySelector('[data-product-admin-alert-list]');
        previewImageNode = document.querySelector('[data-preview-image]');
        previewPlaceholderNode = document.querySelector('[data-preview-placeholder]');

        photoGroup = getInlineGroupById('inline-images-group') || findInlineGroupByHeading('Фото товара');
        videoGroup = getInlineGroupById('inline-videos-group') || findInlineGroupByHeading('Видео товара');
        contentBlockGroup = findInlineGroupByHeading('Блоки подробного описания');
        variantGroup = getInlineGroupById('inline-variants-group') || findInlineGroupByHeading('Варианты товара');
        characteristicsGroup = getInlineGroupById('inline-characteristics-group') || findInlineGroupByHeading('Характеристики');
        stockGroup = getInlineGroupById('inline-stocks-group') || findInlineGroupByHeading('Остатки');
        bundleGroup = getInlineGroupById('inline-bundle_items-group') || findInlineGroupByHeading('комплект');
        descriptionFieldset = document.querySelector('.product-fieldset--description');

        if (photoGroup) photoGroup.classList.add('product-inline-group--photos');
        if (videoGroup) videoGroup.classList.add('product-inline-group--videos');
        if (contentBlockGroup) contentBlockGroup.classList.add('product-inline-group--content-blocks');
        if (variantGroup) variantGroup.classList.add('product-inline-group--variants');
        if (characteristicsGroup) characteristicsGroup.classList.add('product-inline-group--characteristics');
        if (stockGroup) stockGroup.classList.add('product-inline-group--stocks');
        if (bundleGroup) bundleGroup.classList.add('product-inline-group--bundles');

        if (slugInput && !slugInput.placeholder) {
            slugInput.placeholder = 'Сформируется автоматически из названия';
        }

        if (mode === 'add') {
            if (variantGroup) {
                variantGroup.classList.add('product-inline-group--locked');
                ensureLockMessage(
                    variantGroup,
                    'Варианты откроются после первого сохранения',
                    'Сначала сохраните базу карточки и фото. После этого сможете добавлять варианты и задавать для них отдельные цены.'
                );
            }

            if (stockGroup) {
                stockGroup.classList.add('product-inline-group--locked');
                ensureLockMessage(
                    stockGroup,
                    'Остатки доступны после сохранения товара',
                    'Когда товар появится как отдельная запись, можно будет распределить остатки по точкам и вариантам.'
                );
            }

            if (bundleGroup) {
                bundleGroup.classList.add('product-inline-group--locked');
                ensureLockMessage(
                    bundleGroup,
                    'Комплекты подключаются после сохранения',
                    'Связи с комплектами лучше добавлять на втором этапе, когда карточка уже создана.'
                );
            }
        }

        function renderAlerts(items) {
            if (!alertsBox || !alertsList) return;

            alertsList.innerHTML = '';
            if (!items.length) {
                alertsBox.hidden = true;
                return;
            }

            items.forEach(function(item) {
                var li = document.createElement('li');
                li.className = 'product-admin-alert product-admin-alert--' + item.level;
                li.textContent = item.text;
                alertsList.appendChild(li);
            });
            alertsBox.hidden = false;
        }

        function updateFieldHighlight(field, active) {
            var row;

            if (!field) return;
            row = closest(field, '.form-row');
            if (row) row.classList.toggle('product-admin-field-alert', !!active);
            field.classList.toggle('product-admin-input-alert', !!active);
        }

        function updatePreviewImage(group) {
            var previewImage;
            var activeRows;
            var previewUrl = '';

            if (!previewImageNode || !previewPlaceholderNode) return;

            activeRows = getInlineRows(group).filter(function(row) {
                return !isDeletedRow(row) && rowHasImage(row);
            });

            if (activeRows.length) {
                previewImage = activeRows[0].querySelector('.field-image_preview img');
                if (previewImage) {
                    previewUrl = previewImage.getAttribute('src') || '';
                } else {
                    previewUrl = getRowFilePreview(activeRows[0]);
                }
            }

            if (currentPreviewObjectUrl && currentPreviewObjectUrl !== previewUrl && currentPreviewObjectUrl.indexOf('blob:') === 0) {
                window.URL.revokeObjectURL(currentPreviewObjectUrl);
            }
            currentPreviewObjectUrl = previewUrl;

            if (previewUrl) {
                previewImageNode.src = previewUrl;
                previewImageNode.hidden = false;
                previewPlaceholderNode.hidden = true;
                return;
            }

            previewImageNode.hidden = true;
            previewImageNode.removeAttribute('src');
            previewPlaceholderNode.hidden = false;
        }

        function refreshDashboard() {
            refreshScheduled = false;
            var nameValue = nameInput ? nameInput.value.trim() : '';
            var categoryLabel = 'Категория не выбрана';
            var hasCategory = !!(categoryInput && categoryInput.value);
            var priceValue = priceInput ? priceInput.value.trim() : '';
            var photoCount = countActiveRows(photoGroup, rowHasImage);
            var variantCount = countActiveRows(variantGroup, rowHasVariant);
            var stockCount = countActiveRows(stockGroup, rowHasStock);
            var variantPriceOverrideCount = countRowsWithPriceOverride(variantGroup);
            var requiredComplete = 0;
            var progressPercent;
            var missingRequired = [];
            var alerts = [];
            var floatingStatusNode = document.querySelector('[data-product-admin-floating-status]');

            if (nameValue) requiredComplete += 1;
            else missingRequired.push('название');

            if (hasCategory) {
                requiredComplete += 1;
                if (categoryInput.selectedIndex >= 0) {
                    categoryLabel = textContent(categoryInput.options[categoryInput.selectedIndex]) || categoryLabel;
                }
            } else {
                missingRequired.push('категория');
            }

            if (priceValue) requiredComplete += 1;
            else missingRequired.push('цена');

            if (photoCount > 0) requiredComplete += 1;
            else missingRequired.push('фото');

            progressPercent = Math.round((requiredComplete / 4) * 100);

            setText('[data-summary-progress-label]', String(progressPercent) + '%');
            setWidth('[data-summary-progress-bar]', String(progressPercent) + '%');

            if (requiredComplete === 4) {
                setText('[data-summary-progress-text]', 'База карточки готова. Можно сохранять и переходить к вариантам, остаткам и комплектам.');
            } else {
                setText(
                    '[data-summary-progress-text]',
                    'До первого сохранения осталось заполнить: ' + missingRequired.join(', ') + '.'
                );
            }

            setText('[data-preview-name]', nameValue || 'Название не указано');
            setText('[data-preview-category]', categoryLabel);
            setText('[data-preview-price]', priceValue ? priceValue + ' ₽' : 'Цена не указана');
            setText('[data-preview-photos]', 'Фото: ' + String(photoCount));
            setText('[data-preview-variants]', variantCount ? 'Варианты: ' + String(variantCount) : 'Варианты: базовая цена');

            setCheckState('[data-check-name]', nameValue ? 'is-complete' : 'is-pending', nameValue ? 'Заполнено' : 'Обязательно');
            setCheckState('[data-check-category]', hasCategory ? 'is-complete' : 'is-pending', hasCategory ? 'Выбрана' : 'Обязательно');
            setCheckState('[data-check-price]', priceValue ? 'is-complete' : 'is-pending', priceValue ? 'Указана' : 'Обязательно');
            setCheckState('[data-check-photos]', photoCount > 0 ? 'is-complete' : 'is-pending', photoCount > 0 ? String(photoCount) + ' фото' : 'Добавьте фото');

            if (variantCount > 0) {
                setCheckState('[data-check-variants]', 'is-complete', String(variantCount) + ' шт.');
            } else if (optionLabelInput && optionLabelInput.value.trim()) {
                setCheckState('[data-check-variants]', 'is-warning', 'Нужны варианты');
            } else {
                setCheckState('[data-check-variants]', 'is-pending', mode === 'add' ? 'После сохранения' : 'Базовая цена');
            }

            if (stockCount > 0) {
                setCheckState('[data-check-stocks]', 'is-complete', String(stockCount) + ' записей');
            } else {
                setCheckState('[data-check-stocks]', mode === 'add' ? 'is-pending' : 'is-warning', mode === 'add' ? 'После сохранения' : 'Не указаны');
            }

            updateFieldHighlight(nameInput, !nameValue);
            updateFieldHighlight(categoryInput, !hasCategory);
            updateFieldHighlight(priceInput, !priceValue);

            if (!nameValue) {
                alerts.push({ level: 'warning', text: 'Добавьте название товара. Без него карточка не сохранится корректно.' });
            }

            if (!hasCategory) {
                alerts.push({ level: 'warning', text: 'Выберите категорию товара, чтобы карточка попала в нужный раздел каталога.' });
            }

            if (!priceValue) {
                alerts.push({ level: 'warning', text: 'Укажите базовую цену товара. Она нужна даже если часть вариантов будет со своей ценой.' });
            }

            if (photoCount === 0) {
                alerts.push({ level: 'warning', text: 'Пока не добавлено ни одного фото. Для витрины это один из ключевых блоков.' });
            }

            if (optionLabelInput && optionLabelInput.value.trim() && variantCount === 0 && mode !== 'add') {
                alerts.push({ level: 'warning', text: 'Подпись к вариантам заполнена, но сами варианты ещё не добавлены.' });
            }

            if (variantPriceOverrideCount > 0) {
                alerts.push({ level: 'info', text: 'У части вариантов указана своя цена. Базовая цена товара остаётся запасной ценой по умолчанию.' });
            }

            renderAlerts(alerts);
            markPhotoPrimaryRow(photoGroup);
            updatePreviewImage(photoGroup);
            updateSkuFieldState(skuInput, variantCount);
            updateDescriptionMeta(descriptionInput);
            applyContentBlockFieldVisibility(contentBlockGroup);

            if (floatingStatusNode) {
                if (requiredComplete === 4) {
                    floatingStatusNode.textContent = 'База карточки готова. Можно сохранять без возврата к началу страницы.';
                } else {
                    floatingStatusNode.textContent = 'До сохранения базы осталось: ' + missingRequired.join(', ') + '.';
                }
            }
        }

        function scheduleRefresh() {
            if (refreshScheduled) return;
            refreshScheduled = true;
            window.requestAnimationFrame(refreshDashboard);
        }

        function processDeleteCellInRow(row) {
            var deleteCell = row.querySelector('td.delete');
            if (!deleteCell || deleteCell.querySelector('[data-inline-delete-btn]')) return;
            var checkbox = deleteCell.querySelector('input[name$="-DELETE"]');
            if (!checkbox) return;

            checkbox.style.display = 'none';
            var label = deleteCell.querySelector('label');
            if (label) label.style.display = 'none';

            var btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'product-inline-delete-btn';
            btn.setAttribute('data-inline-delete-btn', '');
            btn.setAttribute('aria-label', 'Удалить строку');
            btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M2 2l10 10M12 2L2 12" stroke="currentColor" stroke-width="1.75" stroke-linecap="round"/></svg>';
            if (checkbox.checked) {
                btn.classList.add('is-active');
                row.classList.add('is-marked-delete');
            }
            deleteCell.appendChild(btn);
        }

        function injectAddButton(group) {
            if (group.classList.contains('product-inline-group--locked')) return;
            var tabularEl = group.querySelector('.tabular') || group.querySelector('table');
            if (!tabularEl) return;
            if (tabularEl.previousElementSibling && tabularEl.previousElementSibling.classList.contains('product-inline-add-btn')) return;
            var addRow = group.querySelector('tr.add-row, .add-row');
            var addLink = addRow ? addRow.querySelector('a') : null;
            if (!addLink) return;
            var addBtn = document.createElement('button');
            addBtn.type = 'button';
            addBtn.className = 'product-inline-add-btn';
            addBtn.textContent = '+ Добавить';
            addBtn.addEventListener('click', function() { addLink.click(); });
            tabularEl.parentNode.insertBefore(addBtn, tabularEl);
        }

        function setupInlineEnhancements() {
            var groups = [photoGroup, videoGroup, characteristicsGroup, contentBlockGroup, variantGroup, stockGroup, bundleGroup];

            groups.filter(Boolean).forEach(function(group) {
                if (group.classList.contains('product-inline-group--locked')) return;

                // Process existing rows' delete cells immediately
                getInlineRows(group).forEach(function(row) {
                    processDeleteCellInRow(row);
                });

                // Event delegation: delete button click → toggle checkbox
                group.addEventListener('click', function(e) {
                    var btn = closest(e.target, '[data-inline-delete-btn]');
                    if (!btn) return;
                    var row = closest(btn, 'tr');
                    if (!row) return;
                    var checkbox = row.querySelector('input[name$="-DELETE"]');
                    if (!checkbox) return;
                    checkbox.checked = !checkbox.checked;
                    checkbox.dispatchEvent(new Event('change', { bubbles: true }));
                });

                // Event delegation: checkbox change → toggle visual state
                group.addEventListener('change', function(e) {
                    if (!e.target || !e.target.name || e.target.name.indexOf('-DELETE') === -1) return;
                    var row = closest(e.target, 'tr');
                    if (!row) return;
                    row.classList.toggle('is-marked-delete', e.target.checked);
                    var btn = row.querySelector('[data-inline-delete-btn]');
                    if (btn) btn.classList.toggle('is-active', e.target.checked);
                });

                // Process newly added rows (Django formset adds them dynamically)
                if (window.MutationObserver) {
                    var tbody = group.querySelector('tbody');
                    if (tbody) {
                        new MutationObserver(function(mutations) {
                            mutations.forEach(function(mutation) {
                                Array.prototype.forEach.call(mutation.addedNodes, function(node) {
                                    if (node.nodeType === 1 && node.tagName === 'TR' && !node.classList.contains('empty-form')) {
                                        processDeleteCellInRow(node);
                                    }
                                });
                            });
                        }).observe(tbody, { childList: true });
                    }
                }
            });

            // Defer add-button injection: Django formset JS populates tr.add-row links
            // asynchronously after DOMContentLoaded, so we wait one task.
            setTimeout(function() {
                groups.filter(Boolean).forEach(injectAddButton);
            }, 0);
        }

        function setupTabs() {
            var nav = document.querySelector('[data-product-admin-anchor-nav]');
            if (!nav) return;

            var buttons = Array.prototype.slice.call(nav.querySelectorAll('[data-scroll-target]'));
            if (!buttons.length) return;

            var contentForm = document.querySelector('#content-main form');
            var panelMap = {
                'field-name': contentForm ? Array.prototype.filter.call(
                    contentForm.querySelectorAll('.module'),
                    function(el) { return !closest(el, '.inline-group') && !el.classList.contains('product-fieldset--description'); }
                ) : [],
                'inline-description-group': [descriptionFieldset, characteristicsGroup, contentBlockGroup].filter(Boolean),
                'inline-images-group':      [photoGroup, videoGroup].filter(Boolean),
                'inline-variants-group':    [variantGroup].filter(Boolean),
                'inline-stocks-group':      [stockGroup].filter(Boolean),
                'inline-bundle_items-group':[bundleGroup].filter(Boolean),
            };

            var activeKey = null;

            function activateTab(key) {
                if (!panelMap[key] || activeKey === key) return;
                activeKey = key;

                buttons.forEach(function(btn) {
                    btn.classList.toggle('is-active', btn.getAttribute('data-scroll-target') === key);
                });

                Object.keys(panelMap).forEach(function(panelKey) {
                    panelMap[panelKey].forEach(function(el) {
                        el.hidden = panelKey !== key;
                    });
                });
            }

            buttons.forEach(function(btn) {
                btn.addEventListener('click', function() {
                    if (!btn.disabled) activateTab(btn.getAttribute('data-scroll-target'));
                });
            });

            // Start on first available tab
            buttons.some(function(btn) {
                if (!btn.disabled) {
                    activateTab(btn.getAttribute('data-scroll-target'));
                    return true;
                }
                return false;
            });
        }

        document.addEventListener('click', function(event) {
            var button = closest(event.target, '[data-scroll-target]');
            if (!button || button.disabled) return;
            if (closest(button, '[data-product-admin-anchor-nav]')) return;
            event.preventDefault();
            scrollToTarget(button.getAttribute('data-scroll-target'));
        });

        document.addEventListener('click', function(event) {
            var deleteLink = closest(event.target, '[data-product-admin-delete-link]');
            var message;
            if (!deleteLink) return;
            message = deleteLink.getAttribute('data-confirm-message') || 'Удалить товар? Это действие нельзя отменить.';
            if (!window.confirm(message)) {
                event.preventDefault();
            }
        });

        document.addEventListener('input', scheduleRefresh);
        document.addEventListener('change', scheduleRefresh);

        if (window.MutationObserver) {
            [photoGroup, contentBlockGroup, variantGroup, stockGroup, bundleGroup].filter(Boolean).forEach(function(group) {
                (new MutationObserver(function(mutations) {
                    var shouldRefresh = mutations.some(function(mutation) {
                        return !isInsideManagedPanel(mutation.target);
                    });

                    if (shouldRefresh) {
                        scheduleRefresh();
                    }
                })).observe(group, { childList: true, subtree: true });
            });
        }

        // ── Copy description from another product ──────────────────────────────

        var copyDescModalEl = null;

        function setupCopyDescriptionButton() {
            if (!contentBlockGroup) return;
            if (mode === 'add') return;

            var heading = contentBlockGroup.querySelector('h2');
            if (!heading) return;

            var btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'product-copy-desc-btn';
            btn.textContent = 'Взять описание';
            btn.setAttribute('data-copy-desc-btn', '');
            heading.parentNode.insertBefore(btn, heading.nextSibling);
            btn.addEventListener('click', openCopyDescriptionModal);
        }

        function openCopyDescriptionModal() {
            if (copyDescModalEl) { copyDescModalEl.remove(); copyDescModalEl = null; }

            var searchUrl = (dashboard && dashboard.getAttribute('data-search-url')) || '';
            var blocksUrl = (dashboard && dashboard.getAttribute('data-blocks-url')) || '';

            var modal = document.createElement('div');
            modal.className = 'copy-desc-modal-overlay';
            modal.innerHTML =
                '<div class="copy-desc-modal" role="dialog" aria-modal="true" aria-label="Взять описание из другого товара">' +
                    '<div class="copy-desc-modal__header">' +
                        '<h3 class="copy-desc-modal__title">Взять описание из другого товара</h3>' +
                        '<button type="button" class="copy-desc-modal__close" data-close-modal aria-label="Закрыть">' +
                            '<svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M2 2l12 12M14 2L2 14" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>' +
                        '</button>' +
                    '</div>' +
                    '<div class="copy-desc-modal__body">' +
                        '<div class="copy-desc-modal__search-wrap">' +
                            '<input type="text" class="copy-desc-modal__search vTextField" placeholder="Начните вводить название товара…" autocomplete="off" data-search-input>' +
                            '<p class="copy-desc-modal__search-status" data-search-status></p>' +
                        '</div>' +
                        '<div class="copy-desc-modal__results" data-search-results></div>' +
                        '<div class="copy-desc-modal__preview" data-blocks-preview hidden>' +
                            '<p class="copy-desc-modal__preview-heading" data-preview-heading></p>' +
                            '<div class="copy-desc-modal__preview-blocks" data-preview-blocks></div>' +
                            '<p class="copy-desc-modal__warning">Текущие блоки подробного описания будут заменены.</p>' +
                            '<div class="copy-desc-modal__actions">' +
                                '<button type="button" class="button default copy-desc-modal__confirm" data-confirm-copy>Подтвердить</button>' +
                                '<button type="button" class="button copy-desc-modal__back" data-back-to-search>← Назад</button>' +
                            '</div>' +
                        '</div>' +
                    '</div>' +
                '</div>';
            document.body.appendChild(modal);
            copyDescModalEl = modal;

            var searchInput = modal.querySelector('[data-search-input]');
            var searchStatus = modal.querySelector('[data-search-status]');
            var searchResults = modal.querySelector('[data-search-results]');
            var blocksPreview = modal.querySelector('[data-blocks-preview]');
            var previewHeading = modal.querySelector('[data-preview-heading]');
            var previewBlocks = modal.querySelector('[data-preview-blocks]');
            var confirmBtn = modal.querySelector('[data-confirm-copy]');
            var backBtn = modal.querySelector('[data-back-to-search]');
            var selectedBlocks = null;
            var searchTimer = null;

            function closeModal() {
                if (copyDescModalEl) { copyDescModalEl.remove(); copyDescModalEl = null; }
            }

            modal.querySelector('[data-close-modal]').addEventListener('click', closeModal);
            modal.addEventListener('click', function(e) { if (e.target === modal) closeModal(); });
            document.addEventListener('keydown', function onEsc(e) {
                if (e.key === 'Escape') { closeModal(); document.removeEventListener('keydown', onEsc); }
            });

            function showSearchPanel() {
                searchResults.hidden = false;
                blocksPreview.hidden = true;
                selectedBlocks = null;
            }

            function doSearch(q) {
                q = q.trim();
                if (q.length < 2) { searchResults.innerHTML = ''; searchStatus.textContent = ''; return; }
                searchStatus.textContent = 'Поиск…';
                searchResults.innerHTML = '';
                var xhr = new XMLHttpRequest();
                xhr.open('GET', searchUrl + '?q=' + encodeURIComponent(q));
                xhr.onload = function() {
                    searchStatus.textContent = '';
                    if (xhr.status !== 200) { searchStatus.textContent = 'Ошибка поиска.'; return; }
                    var products;
                    try { products = JSON.parse(xhr.responseText); } catch (e) { return; }
                    if (!products.length) {
                        searchResults.innerHTML = '<p class="copy-desc-no-results">Товары не найдены</p>';
                        return;
                    }
                    var html = '<ul class="copy-desc-modal__result-list">';
                    products.forEach(function(p) {
                        html += '<li class="copy-desc-modal__result-item" data-product-id="' + p.id + '" data-product-name="' + escapeHtml(p.name) + '">' +
                            '<span class="copy-desc-modal__result-name">' + escapeHtml(p.name) + '</span>' +
                            '<span class="copy-desc-modal__result-meta">' + escapeHtml(p.category) + '</span>' +
                            '</li>';
                    });
                    html += '</ul>';
                    searchResults.innerHTML = html;
                };
                xhr.onerror = function() { searchStatus.textContent = 'Ошибка сети.'; };
                xhr.send();
            }

            searchInput.addEventListener('input', function() {
                clearTimeout(searchTimer);
                searchTimer = setTimeout(function() { doSearch(searchInput.value); }, 300);
            });

            searchResults.addEventListener('click', function(e) {
                var item = closest(e.target, '[data-product-id]');
                if (!item) return;
                var productId = item.getAttribute('data-product-id');
                var productName = item.getAttribute('data-product-name');
                fetchBlocks(productId, productName);
            });

            function fetchBlocks(productId, productName) {
                searchStatus.textContent = 'Загрузка блоков…';
                var url = blocksUrl.replace('/0/', '/' + productId + '/');
                var xhr = new XMLHttpRequest();
                xhr.open('GET', url);
                xhr.onload = function() {
                    searchStatus.textContent = '';
                    if (xhr.status !== 200) { searchStatus.textContent = 'Ошибка загрузки.'; return; }
                    var data;
                    try { data = JSON.parse(xhr.responseText); } catch (e) { return; }
                    selectedBlocks = data.blocks;
                    showPreview(productName, data.blocks);
                };
                xhr.onerror = function() { searchStatus.textContent = 'Ошибка сети.'; };
                xhr.send();
            }

            function showPreview(productName, blocks) {
                searchResults.hidden = true;
                blocksPreview.hidden = false;
                var n = blocks.length;
                var word = n === 1 ? 'блок' : n < 5 ? 'блока' : 'блоков';
                previewHeading.innerHTML = 'Из товара <strong>' + escapeHtml(productName) + '</strong>: ' + n + '\u00a0' + word;
                var html = '';
                blocks.forEach(function(block) {
                    html += '<div class="copy-desc-modal__block-preview">';
                    html += '<span class="copy-desc-modal__block-type">' + escapeHtml(blockTypeLabel(block.block_type)) + '</span>';
                    if (block.title) html += '<div class="copy-desc-modal__block-title">' + escapeHtml(block.title) + '</div>';
                    if (block.text) {
                        var preview = block.text.length > 200 ? block.text.substring(0, 200) + '\u2026' : block.text;
                        html += '<div class="copy-desc-modal__block-text">' + escapeHtml(preview) + '</div>';
                    }
                    if (!block.title && !block.text) {
                        html += '<div class="copy-desc-modal__block-text copy-desc-modal__block-text--muted">(нет текста — ' + escapeHtml(blockTypeLabel(block.block_type)) + ')</div>';
                    }
                    html += '</div>';
                });
                previewBlocks.innerHTML = html;
            }

            backBtn.addEventListener('click', showSearchPanel);

            confirmBtn.addEventListener('click', function() {
                if (!selectedBlocks) return;
                applyContentBlocks(selectedBlocks);
                closeModal();
            });

            searchInput.focus();
        }

        function setInlineField(container, prefix, index, fieldName, value) {
            var el = container.querySelector('[name="' + prefix + '-' + index + '-' + fieldName + '"]');
            if (!el) return;
            if (el.type === 'checkbox') {
                el.checked = !!value;
            } else {
                el.value = (value != null) ? String(value) : '';
            }
        }

        function applyContentBlocks(blocks) {
            if (!contentBlockGroup) return;

            // Mark all existing rows for deletion
            getStackedInlineRows(contentBlockGroup).forEach(function(row) {
                var cb = row.querySelector('input[name$="-DELETE"]');
                if (cb && !cb.checked) {
                    cb.checked = true;
                    cb.dispatchEvent(new Event('change', { bubbles: true }));
                }
            });

            // Find empty form template and derive prefix
            var emptyForm = contentBlockGroup.querySelector('.empty-form');
            if (!emptyForm || !emptyForm.id) return;
            var prefix = emptyForm.id.replace('-empty', '');

            var totalInput = document.querySelector('input[name="' + prefix + '-TOTAL_FORMS"]');
            if (!totalInput) return;
            var startIndex = parseInt(totalInput.value, 10) || 0;

            blocks.forEach(function(block, i) {
                var idx = startIndex + i;
                var clone = emptyForm.cloneNode(true);
                clone.classList.remove('empty-form', 'last-related');
                clone.removeAttribute('id');
                clone.hidden = false;
                clone.style.display = '';

                // Replace __prefix__ placeholder with actual index in all relevant attributes
                clone.querySelectorAll('[name]').forEach(function(el) {
                    el.name = el.name.replace(/__prefix__/g, idx);
                });
                clone.querySelectorAll('[id]').forEach(function(el) {
                    el.id = el.id.replace(/__prefix__/g, idx);
                });
                clone.querySelectorAll('[for]').forEach(function(el) {
                    el.setAttribute('for', el.getAttribute('for').replace(/__prefix__/g, idx));
                });

                setInlineField(clone, prefix, idx, 'block_type', block.block_type || 'text');
                setInlineField(clone, prefix, idx, 'title', block.title || '');
                setInlineField(clone, prefix, idx, 'text', block.text || '');
                setInlineField(clone, prefix, idx, 'sort_order', block.sort_order != null ? block.sort_order : i);
                setInlineField(clone, prefix, idx, 'is_active', true);
                setInlineField(clone, prefix, idx, 'image_position', block.image_position || 'left');
                setInlineField(clone, prefix, idx, 'caption', block.caption || '');
                setInlineField(clone, prefix, idx, 'rutube_url', block.rutube_url || '');

                emptyForm.parentNode.insertBefore(clone, emptyForm);
            });

            totalInput.value = startIndex + blocks.length;
            totalInput.dispatchEvent(new Event('change', { bubbles: true }));
            applyContentBlockFieldVisibility(contentBlockGroup);
            scheduleRefresh();
        }

        // ─────────────────────────────────────────────────────────────────────

        setupTagsWidget();
        setupImagePreviewLightbox();
        setupTabs();
        refreshDashboard();
        setupInlineEnhancements();
        setupCopyDescriptionButton();
    });
})();
