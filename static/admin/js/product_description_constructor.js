(function() {
  'use strict';

  function getCsrfToken() {
    var input = document.querySelector('input[name="csrfmiddlewaretoken"]');
    return input ? input.value : '';
  }

  function escapeHtml(value) {
    return String(value || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  function clone(value) {
    try {
      return JSON.parse(JSON.stringify(value || {}));
    } catch (error) {
      return {};
    }
  }

  function readState(root) {
    var payloadNode = root.querySelector('[data-pdc-payload]');
    try {
      return JSON.parse(payloadNode && payloadNode.value ? payloadNode.value : '{}') || {};
    } catch (error) {
      return {};
    }
  }

  function setMessage(root, text, kind) {
    var node = root.querySelector('[data-pdc-message]');
    if (!node) return;
    node.textContent = text || '';
    node.className = 'product-description-constructor__message';
    if (kind) node.classList.add('is-' + kind);
  }

  function normalizeDescription(description) {
    description = description || {};
    description.blocks = Array.isArray(description.blocks) ? description.blocks : [];
    description.status = description.status === 'published' ? 'published' : 'draft';
    description.source = description.source || 'custom';
    description.title = description.title || '';
    description.intro = description.intro || '';
    description.is_active = !!description.is_active;
    return description;
  }

  function visibleBlocks(description) {
    return (description.blocks || []).filter(function(block) { return !block.deleted; });
  }

  function blockLabel(block, blockTypesBySlug) {
    var type = blockTypesBySlug[block.block_type] || {};
    var data = block.data || {};
    return data.title || block.slot_key || type.name || block.block_type || 'Блок';
  }

  function templateBlockLabel(slot) {
    return slot.label || slot.block_type_name || slot.block_type || 'Блок';
  }

  function init(root) {
    var initialState = readState(root);
    var state = {
      templates: initialState.templates || [],
      blockTypes: initialState.blockTypes || [],
      description: normalizeDescription(initialState.description || {})
    };
    var blockTypesBySlug = {};
    state.blockTypes.forEach(function(type) {
      blockTypesBySlug[type.slug] = type;
    });

    var payloadNode = root.querySelector('[data-pdc-payload]');
    var templateList = root.querySelector('[data-pdc-template-list]');
    var blockTypeSelect = root.querySelector('[data-pdc-block-type-select]');
    var startEmptyButton = root.querySelector('[data-pdc-start-empty]');
    var addBlockButton = root.querySelector('[data-pdc-add-block]');
    var previewButton = root.querySelector('[data-pdc-preview]');
    var titleInput = root.querySelector('[data-pdc-title]');
    var introInput = root.querySelector('[data-pdc-intro]');
    var statusInput = root.querySelector('[data-pdc-status]');
    var activeInput = root.querySelector('[data-pdc-active]');
    var blockList = root.querySelector('[data-pdc-block-list]');
    var blockEditor = root.querySelector('[data-pdc-block-editor]');
    var previewTarget = root.querySelector('[data-pdc-preview-target]');
    var applyUrl = root.getAttribute('data-apply-url');
    var previewUrl = root.getAttribute('data-preview-url');
    var selectedClientId = null;
    var previewTimer = null;

    function currentPayload() {
      state.description.title = titleInput ? titleInput.value : state.description.title;
      state.description.intro = introInput ? introInput.value : state.description.intro;
      state.description.status = statusInput ? statusInput.value : state.description.status;
      state.description.is_active = activeInput ? activeInput.checked : state.description.is_active;
      visibleBlocks(state.description).forEach(function(block, index) {
        block.sort_order = (index + 1) * 10;
      });
      return state.description;
    }

    function syncPayload() {
      if (payloadNode) {
        payloadNode.value = JSON.stringify(currentPayload());
      }
    }

    function schedulePreview() {
      window.clearTimeout(previewTimer);
      previewTimer = window.setTimeout(renderPreview, 700);
    }

    function findTemplate(templateId) {
      return (state.templates || []).find(function(template) {
        return String(template.id) === String(templateId);
      }) || null;
    }

    function renderTemplateCards() {
      if (!templateList) return;
      if (!state.templates.length) {
        templateList.innerHTML = '<p class="product-description-constructor__empty">Активных шаблонов пока нет. Можно начать с пустого описания или собрать блоки вручную.</p>';
        return;
      }
      templateList.innerHTML = state.templates.map(function(template) {
        var slots = Array.isArray(template.slots) ? template.slots : [];
        var slotsHtml = slots.length
          ? slots.map(function(slot) {
              var required = slot.is_required ? ' · обязательный' : '';
              var helpText = slot.help_text ? '<em>' + escapeHtml(slot.help_text) + '</em>' : '';
              return '' +
                '<li>' +
                  '<span>' + escapeHtml(templateBlockLabel(slot)) + '</span>' +
                  '<small>' + escapeHtml(slot.block_type_name || slot.block_type || 'Блок') + escapeHtml(required) + '</small>' +
                  helpText +
                '</li>';
            }).join('')
          : '<li><span>Без готовых блоков</span><small>Пустая структура</small></li>';
        return '' +
          '<article class="product-description-constructor__template-card' + (String(state.description.template_id || '') === String(template.id) ? ' is-current' : '') + '">' +
            '<div class="product-description-constructor__template-card-head">' +
              '<div>' +
                '<strong>' + escapeHtml(template.name) + '</strong>' +
                (template.category ? '<span>' + escapeHtml(template.category) + '</span>' : '') +
              '</div>' +
              '<small>v' + escapeHtml(template.version || 1) + '</small>' +
            '</div>' +
            '<p>' + escapeHtml(template.description || 'Готовая структура подробного описания.') + '</p>' +
            '<ol>' + slotsHtml + '</ol>' +
            '<div class="product-description-constructor__template-actions">' +
              '<button type="button" class="button" data-pdc-apply-template="' + escapeHtml(template.id) + '">Применить шаблон</button>' +
              '<button type="button" class="button" data-pdc-preview-template="' + escapeHtml(template.id) + '">Предпросмотр</button>' +
            '</div>' +
          '</article>';
      }).join('');
    }

    function renderBlockTypeOptions() {
      if (!blockTypeSelect) return;
      var html = '';
      state.blockTypes.forEach(function(type) {
        html += '<option value="' + escapeHtml(type.slug) + '">' + escapeHtml(type.name) + '</option>';
      });
      blockTypeSelect.innerHTML = html;
    }

    function renderMeta() {
      if (titleInput) titleInput.value = state.description.title || '';
      if (introInput) introInput.value = state.description.intro || '';
      if (statusInput) statusInput.value = state.description.status || 'draft';
      if (activeInput) activeInput.checked = !!state.description.is_active;
    }

    function renderBlockList() {
      if (!blockList) return;
      var blocks = visibleBlocks(state.description);
      if (!blocks.length) {
        blockList.innerHTML = '<p class="product-description-constructor__empty">Блоков пока нет.</p>';
        selectedClientId = null;
        renderBlockEditor();
        syncPayload();
        return;
      }
      if (!selectedClientId || !blocks.some(function(block) { return block.client_id === selectedClientId; })) {
        selectedClientId = blocks[0].client_id;
      }
      blockList.innerHTML = blocks.map(function(block, index) {
        var type = blockTypesBySlug[block.block_type] || {};
        return '' +
          '<article class="product-description-constructor__block' + (block.client_id === selectedClientId ? ' is-selected' : '') + '" data-client-id="' + escapeHtml(block.client_id) + '">' +
            '<button type="button" data-pdc-select-block="' + escapeHtml(block.client_id) + '">' +
              '<strong>' + escapeHtml(blockLabel(block, blockTypesBySlug)) + '</strong>' +
              '<span>' + escapeHtml(type.name || block.block_type) + (block.is_active ? '' : ' · скрыт') + '</span>' +
            '</button>' +
            '<div class="product-description-constructor__block-actions">' +
              '<button type="button" class="button" data-pdc-move-up="' + escapeHtml(block.client_id) + '"' + (index === 0 ? ' disabled' : '') + '>↑</button>' +
              '<button type="button" class="button" data-pdc-move-down="' + escapeHtml(block.client_id) + '"' + (index === blocks.length - 1 ? ' disabled' : '') + '>↓</button>' +
              '<button type="button" class="button" data-pdc-delete="' + escapeHtml(block.client_id) + '">Удалить</button>' +
            '</div>' +
          '</article>';
      }).join('');
      renderBlockEditor();
      syncPayload();
    }

    function templatePreviewPayload(template) {
      return normalizeDescription({
        id: null,
        template_id: template.id,
        title: template.name || '',
        intro: template.description || '',
        status: 'draft',
        is_active: false,
        source: 'template',
        blocks: (template.slots || []).map(function(slot) {
          return {
            id: null,
            client_id: 'preview-template-' + template.id + '-' + slot.slot_key,
            slot_key: slot.slot_key,
            block_type: slot.block_type,
            block_type_name: slot.block_type_name,
            sort_order: slot.sort_order,
            is_active: true,
            data: clone(slot.default_data),
            deleted: false
          };
        })
      });
    }

    function selectedBlock() {
      return visibleBlocks(state.description).find(function(block) { return block.client_id === selectedClientId; }) || null;
    }

    function dataTextareaValue(block) {
      try {
        return JSON.stringify(block.data || {}, null, 2);
      } catch (error) {
        return '{}';
      }
    }

    function renderBlockEditor() {
      if (!blockEditor) return;
      var block = selectedBlock();
      if (!block) {
        blockEditor.innerHTML = '<p>Выберите блок слева или добавьте новый.</p>';
        return;
      }
      var type = blockTypesBySlug[block.block_type] || {};
      var data = block.data || {};
      blockEditor.innerHTML = '' +
        '<div class="product-description-constructor__block-editor-head">' +
          '<strong>' + escapeHtml(type.name || block.block_type) + '</strong>' +
          '<label><input type="checkbox" data-pdc-block-active ' + (block.is_active ? 'checked' : '') + '> Активен</label>' +
        '</div>' +
        '<label>Ключ блока <input type="text" data-pdc-block-slot value="' + escapeHtml(block.slot_key || '') + '"></label>' +
        '<label>Быстрый заголовок <input type="text" data-pdc-block-title value="' + escapeHtml(data.title || '') + '"></label>' +
        '<label>Быстрый текст <textarea data-pdc-block-text rows="4">' + escapeHtml(data.text || data.lead || '') + '</textarea></label>' +
        '<label>JSON данных блока <textarea data-pdc-block-json rows="12" spellcheck="false">' + escapeHtml(dataTextareaValue(block)) + '</textarea></label>';
    }

    function findBlock(clientId) {
      return (state.description.blocks || []).find(function(block) { return block.client_id === clientId; });
    }

    function addBlock(blockTypeSlug) {
      var type = blockTypesBySlug[blockTypeSlug];
      if (!type) return;
      var nextIndex = visibleBlocks(state.description).length + 1;
      var clientId = 'new-' + Date.now() + '-' + Math.round(Math.random() * 10000);
      var block = {
        id: null,
        client_id: clientId,
        slot_key: blockTypeSlug + '-' + nextIndex,
        block_type: blockTypeSlug,
        block_type_name: type.name,
        sort_order: nextIndex * 10,
        is_active: true,
        data: clone(type.default_data),
        deleted: false
      };
      state.description.blocks.push(block);
      selectedClientId = clientId;
      renderBlockList();
      schedulePreview();
    }

    function moveBlock(clientId, direction) {
      var blocks = visibleBlocks(state.description);
      var index = blocks.findIndex(function(block) { return block.client_id === clientId; });
      var targetIndex = index + direction;
      if (index < 0 || targetIndex < 0 || targetIndex >= blocks.length) return;
      var actual = state.description.blocks;
      var a = actual.indexOf(blocks[index]);
      var b = actual.indexOf(blocks[targetIndex]);
      var tmp = actual[a];
      actual[a] = actual[b];
      actual[b] = tmp;
      renderBlockList();
      schedulePreview();
    }

    function deleteBlock(clientId) {
      var block = findBlock(clientId);
      if (!block) return;
      if (block.id) {
        block.deleted = true;
      } else {
        state.description.blocks = state.description.blocks.filter(function(item) { return item.client_id !== clientId; });
      }
      selectedClientId = null;
      renderBlockList();
      schedulePreview();
    }

    function applyTemplate(payload) {
      state.description = normalizeDescription(payload || {});
      selectedClientId = null;
      renderMeta();
      renderTemplateCards();
      renderBlockList();
      syncPayload();
      schedulePreview();
    }

    function startEmptyDescription() {
      state.description = normalizeDescription({
        id: null,
        template_id: null,
        title: '',
        intro: '',
        status: 'draft',
        is_active: false,
        source: 'custom',
        blocks: []
      });
      selectedClientId = null;
      renderMeta();
      renderTemplateCards();
      renderBlockList();
      syncPayload();
      if (previewTarget) previewTarget.innerHTML = '<p>Пустое описание загружено в редактор. Сохраните товар, чтобы записать изменения.</p>';
      setMessage(root, 'Пустая заготовка загружена. Сохраните товар, чтобы записать изменения.', 'success');
    }

    function applyTemplateById(templateId) {
      if (!templateId) {
        setMessage(root, 'Выберите шаблон.', 'error');
        return;
      }
      if (visibleBlocks(state.description).length && !window.confirm('Применить шаблон и заменить текущие блоки подробного описания?')) {
        return;
      }
      fetch(applyUrl, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': getCsrfToken()
        },
        body: JSON.stringify({template_id: templateId})
      })
        .then(function(response) { return response.json(); })
        .then(function(data) {
          if (data.error) throw new Error(data.error);
          applyTemplate(data.payload);
          setMessage(root, 'Шаблон применён в редакторе. Сохраните товар, чтобы записать изменения.', 'success');
        })
        .catch(function(error) {
          setMessage(root, error.message || 'Не удалось применить шаблон.', 'error');
        });
    }

    function renderPayloadPreview(payload, successMessage) {
      if (!previewUrl) return;
      fetch(previewUrl, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': getCsrfToken()
        },
        body: JSON.stringify(payload)
      })
        .then(function(response) { return response.json(); })
        .then(function(data) {
          if (data.error) throw new Error(data.error);
          if (previewTarget) previewTarget.innerHTML = data.html || '<p>Нет данных для предпросмотра.</p>';
          setMessage(root, successMessage || 'Предпросмотр обновлён.', 'success');
        })
        .catch(function(error) {
          setMessage(root, error.message || 'Не удалось построить предпросмотр.', 'error');
        });
    }

    function renderPreview() {
      syncPayload();
      renderPayloadPreview(currentPayload(), 'Предпросмотр текущего описания обновлён.');
    }

    renderTemplateCards();
    renderBlockTypeOptions();
    renderMeta();
    renderBlockList();

    [titleInput, introInput, statusInput, activeInput].forEach(function(input) {
      if (!input) return;
      input.addEventListener('input', function() {
        syncPayload();
        schedulePreview();
      });
      input.addEventListener('change', function() {
        syncPayload();
        schedulePreview();
      });
    });

    if (templateList) {
      templateList.addEventListener('click', function(event) {
        var applyTemplateButton = event.target.closest('[data-pdc-apply-template]');
        var previewTemplateButton = event.target.closest('[data-pdc-preview-template]');
        if (applyTemplateButton) {
          applyTemplateById(applyTemplateButton.getAttribute('data-pdc-apply-template'));
        } else if (previewTemplateButton) {
          var template = findTemplate(previewTemplateButton.getAttribute('data-pdc-preview-template'));
          if (!template) return;
          renderPayloadPreview(templatePreviewPayload(template), 'Предпросмотр шаблона обновлён. Редактор не изменён.');
        }
      });
    }

    if (startEmptyButton) {
      startEmptyButton.addEventListener('click', function() {
        if (visibleBlocks(state.description).length && !window.confirm('Начать с пустого описания и заменить текущие блоки в редакторе?')) {
          return;
        }
        startEmptyDescription();
      });
    }

    if (addBlockButton) {
      addBlockButton.addEventListener('click', function() {
        addBlock(blockTypeSelect && blockTypeSelect.value);
      });
    }

    if (previewButton) {
      previewButton.addEventListener('click', renderPreview);
    }

    if (blockList) {
      blockList.addEventListener('click', function(event) {
        var selectButton = event.target.closest('[data-pdc-select-block]');
        var upButton = event.target.closest('[data-pdc-move-up]');
        var downButton = event.target.closest('[data-pdc-move-down]');
        var deleteButton = event.target.closest('[data-pdc-delete]');
        if (selectButton) {
          selectedClientId = selectButton.getAttribute('data-pdc-select-block');
          renderBlockList();
        } else if (upButton) {
          moveBlock(upButton.getAttribute('data-pdc-move-up'), -1);
        } else if (downButton) {
          moveBlock(downButton.getAttribute('data-pdc-move-down'), 1);
        } else if (deleteButton) {
          deleteBlock(deleteButton.getAttribute('data-pdc-delete'));
        }
      });
    }

    if (blockEditor) {
      blockEditor.addEventListener('input', function(event) {
        var block = selectedBlock();
        if (!block) return;
        if (event.target.matches('[data-pdc-block-slot]')) {
          block.slot_key = event.target.value;
        } else if (event.target.matches('[data-pdc-block-title]')) {
          block.data = block.data || {};
          block.data.title = event.target.value;
          var jsonNode = blockEditor.querySelector('[data-pdc-block-json]');
          if (jsonNode) jsonNode.value = dataTextareaValue(block);
        } else if (event.target.matches('[data-pdc-block-text]')) {
          block.data = block.data || {};
          if (block.block_type === 'hero_summary') {
            block.data.lead = event.target.value;
          } else {
            block.data.text = event.target.value;
          }
          var jsonNode2 = blockEditor.querySelector('[data-pdc-block-json]');
          if (jsonNode2) jsonNode2.value = dataTextareaValue(block);
        } else if (event.target.matches('[data-pdc-block-json]')) {
          try {
            block.data = JSON.parse(event.target.value || '{}') || {};
            setMessage(root, '', '');
          } catch (error) {
            setMessage(root, 'JSON блока пока некорректный, он не будет сохранён до исправления.', 'error');
            return;
          }
        }
        syncPayload();
        schedulePreview();
      });
      blockEditor.addEventListener('change', function(event) {
        var block = selectedBlock();
        if (!block) return;
        if (event.target.matches('[data-pdc-block-active]')) {
          block.is_active = event.target.checked;
          renderBlockList();
          schedulePreview();
        }
      });
    }

    var form = root.closest('form');
    if (form) {
      form.addEventListener('submit', syncPayload);
    }
    syncPayload();
  }

  document.addEventListener('DOMContentLoaded', function() {
    document.querySelectorAll('[data-product-description-constructor]').forEach(init);
  });
})();
