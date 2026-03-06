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
            if (targetKey === 'inline-images-group') target = findInlineGroupByHeading('Фото товара');
            if (targetKey === 'inline-variants-group') target = findInlineGroupByHeading('Варианты товара');
            if (targetKey === 'inline-characteristics-group') target = findInlineGroupByHeading('Характеристики');
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

    onReady(function() {
        var dashboard = document.querySelector('[data-product-admin-dashboard]');
        var refreshScheduled = false;
        var mode;
        var nameInput;
        var categoryInput;
        var priceInput;
        var optionLabelInput;
        var slugInput;
        var alertsBox;
        var alertsList;
        var photoGroup;
        var variantGroup;
        var stockGroup;
        var bundleGroup;
        var previewImageNode;
        var previewPlaceholderNode;
        var currentPreviewObjectUrl = '';

        if (!dashboard) return;

        mode = dashboard.getAttribute('data-mode');
        nameInput = document.getElementById('id_name');
        categoryInput = document.getElementById('id_category');
        priceInput = document.getElementById('id_price');
        optionLabelInput = document.getElementById('id_option_label');
        slugInput = document.getElementById('id_slug');
        alertsBox = document.querySelector('[data-product-admin-alerts]');
        alertsList = document.querySelector('[data-product-admin-alert-list]');
        previewImageNode = document.querySelector('[data-preview-image]');
        previewPlaceholderNode = document.querySelector('[data-preview-placeholder]');

        photoGroup = getInlineGroupById('inline-images-group') || findInlineGroupByHeading('Фото товара');
        variantGroup = getInlineGroupById('inline-variants-group') || findInlineGroupByHeading('Варианты товара');
        stockGroup = getInlineGroupById('inline-stocks-group') || findInlineGroupByHeading('Остатки');
        bundleGroup = getInlineGroupById('inline-bundle_items-group') || findInlineGroupByHeading('комплект');

        if (photoGroup) photoGroup.classList.add('product-inline-group--photos');
        if (variantGroup) variantGroup.classList.add('product-inline-group--variants');
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
        }

        function scheduleRefresh() {
            if (refreshScheduled) return;
            refreshScheduled = true;
            window.requestAnimationFrame(refreshDashboard);
        }

        document.addEventListener('click', function(event) {
            var button = closest(event.target, '[data-scroll-target]');
            if (!button || button.disabled) return;
            event.preventDefault();
            scrollToTarget(button.getAttribute('data-scroll-target'));
        });

        document.addEventListener('input', scheduleRefresh);
        document.addEventListener('change', scheduleRefresh);

        if (window.MutationObserver) {
            [photoGroup, variantGroup, stockGroup, bundleGroup].filter(Boolean).forEach(function(group) {
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

        refreshDashboard();
    });
})();
