import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Card, Button, Badge, Input, Select } from '../components/ui';
import { Icons } from '../constants';
import { ContractType, Template, TemplateVariable } from '../types';
import { CreateTemplatePayload, UpdateTemplatePayload } from '../services/api';

interface TemplatesProps {
  templates: Template[];
  templateVariables?: TemplateVariable[];
  onCreateTemplate: (payload: CreateTemplatePayload) => Promise<Template>;
  onUpdateTemplate: (templateId: string, payload: UpdateTemplatePayload) => Promise<Template>;
  onDeleteTemplate: (templateId: string) => Promise<void>;
}

type TemplateFormMode = 'create' | 'edit' | null;

interface TemplateFormData {
  name: string;
  type: ContractType;
  isActive: boolean;
  contractText: string;
  content: string;
  css: string;
}

type EditorMode = 'simple' | 'advanced';

const TEMPLATE_TYPE_OPTIONS = [
  { value: ContractType.SERVICE, label: ContractType.SERVICE },
  { value: ContractType.SUPPLY, label: ContractType.SUPPLY },
  { value: ContractType.NDA, label: ContractType.NDA },
  { value: ContractType.RENTAL, label: ContractType.RENTAL },
];

const createEmptyTemplateForm = (): TemplateFormData => ({
  name: '',
  type: ContractType.SERVICE,
  isActive: true,
  contractText: '',
  content: '',
  css: '',
});

const SIMPLE_TEMPLATE_MARKER = '<!--DOCUFLOW_SIMPLE_TEMPLATE-->';

const escapeHtml = (value: string) =>
  String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');

const decodeHtmlEntities = (value: string) =>
  String(value)
    .replace(/&nbsp;/g, ' ')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&#39;/g, "'")
    .replace(/&quot;/g, '"');

const isSimpleTextTemplate = (content: string) => String(content || '').includes(SIMPLE_TEMPLATE_MARKER);

const templateContentToPlainText = (content: string) => {
  const normalized = String(content || '')
    .replace(SIMPLE_TEMPLATE_MARKER, '')
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<\/(p|h1|h2|h3|li|tr|div|section|article|table|thead|tbody|ul|ol)>/gi, '\n')
    .replace(/<li[^>]*>/gi, '- ')
    .replace(/<[^>]+>/g, '')
    .replace(/\r/g, '')
    .replace(/\n{3,}/g, '\n\n')
    .trim();

  return decodeHtmlEntities(normalized);
};

const buildSimpleTemplateHtml = (contractText: string) => {
  const lines = String(contractText || '').replace(/\r/g, '').split('\n');
  const blocks: string[] = [];
  let listItems: string[] = [];

  const flushList = () => {
    if (listItems.length === 0) {
      return;
    }

    blocks.push(
      `<ul>\n${listItems
        .map((item) => `  <li>${escapeHtml(item)}</li>`)
        .join('\n')}\n</ul>`,
    );
    listItems = [];
  };

  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line) {
      flushList();
      continue;
    }

    if (line.startsWith('- ') || line.startsWith('* ')) {
      listItems.push(line.slice(2).trim());
      continue;
    }

    flushList();

    if (line.startsWith('### ')) {
      blocks.push(`<h3>${escapeHtml(line.slice(4).trim())}</h3>`);
      continue;
    }

    if (line.startsWith('## ')) {
      blocks.push(`<h2>${escapeHtml(line.slice(3).trim())}</h2>`);
      continue;
    }

    if (line.startsWith('# ')) {
      blocks.push(`<h1>${escapeHtml(line.slice(2).trim())}</h1>`);
      continue;
    }

    blocks.push(`<p>${escapeHtml(line)}</p>`);
  }

  flushList();

  const content = blocks.length > 0 ? blocks.join('\n    ') : '<p></p>';
  return `${SIMPLE_TEMPLATE_MARKER}
<div class="document-page contract-text-template">
    ${content}
</div>`;
};

const templateToForm = (template: Template): TemplateFormData => ({
  name: template.name || '',
  type: template.type,
  isActive: Boolean(template.isActive),
  contractText: templateContentToPlainText(template.content || ''),
  content: template.content || '',
  css: template.css || '',
});

export const Templates: React.FC<TemplatesProps> = ({
  templates,
  templateVariables = [],
  onCreateTemplate,
  onUpdateTemplate,
  onDeleteTemplate,
}) => {
  const [formMode, setFormMode] = useState<TemplateFormMode>(null);
  const [editingTemplateId, setEditingTemplateId] = useState<string | null>(null);
  const [formData, setFormData] = useState<TemplateFormData>(createEmptyTemplateForm);
  const [editorMode, setEditorMode] = useState<EditorMode>('simple');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const simpleEditorRef = useRef<HTMLTextAreaElement | null>(null);

  const activeTemplatesCount = useMemo(
    () => templates.filter((template) => template.isActive).length,
    [templates],
  );
  const availableTemplateTokens = useMemo(
    () =>
      templateVariables
        .map((item) => ({ key: String(item.key || '').trim(), label: String(item.description || item.key || '').trim() }))
        .filter((item) => item.key.length > 0),
    [templateVariables],
  );

  useEffect(() => {
    if (!editingTemplateId) {
      return;
    }

    const exists = templates.some((template) => template.id === editingTemplateId);
    if (!exists) {
      setFormMode(null);
      setEditingTemplateId(null);
      setFormData(createEmptyTemplateForm());
    }
  }, [editingTemplateId, templates]);

  const startCreate = () => {
    setFormMode('create');
    setEditingTemplateId(null);
    setFormData(createEmptyTemplateForm());
    setEditorMode('simple');
    setErrorMessage(null);
    setSuccessMessage(null);
  };

  const startEdit = (template: Template) => {
    const nextMode: EditorMode = isSimpleTextTemplate(template.content || '') ? 'simple' : 'advanced';
    setFormMode('edit');
    setEditingTemplateId(template.id);
    setFormData(templateToForm(template));
    setEditorMode(nextMode);
    setErrorMessage(null);
    setSuccessMessage(null);
  };

  const closeForm = () => {
    setFormMode(null);
    setEditingTemplateId(null);
    setFormData(createEmptyTemplateForm());
    setEditorMode('simple');
    setErrorMessage(null);
  };

  const insertToken = (tokenKey: string) => {
    const token = `{{${tokenKey}}}`;
    const textarea = simpleEditorRef.current;

    if (!textarea) {
      setFormData((prev) => ({ ...prev, contractText: `${prev.contractText}${prev.contractText ? ' ' : ''}${token}` }));
      return;
    }

    const start = textarea.selectionStart ?? textarea.value.length;
    const end = textarea.selectionEnd ?? textarea.value.length;

    setFormData((prev) => {
      const nextValue = `${prev.contractText.slice(0, start)}${token}${prev.contractText.slice(end)}`;
      return { ...prev, contractText: nextValue };
    });

    requestAnimationFrame(() => {
      textarea.focus();
      const nextCursor = start + token.length;
      textarea.setSelectionRange(nextCursor, nextCursor);
    });
  };

  const saveTemplate = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const normalizedName = formData.name.trim();
    if (!normalizedName) {
      setErrorMessage('Укажите название шаблона.');
      return;
    }

    if (editorMode === 'simple' && !formData.contractText.trim()) {
      setErrorMessage('Введите текст договора.');
      return;
    }

    if (editorMode === 'advanced' && !formData.content.trim()) {
      setErrorMessage('Введите HTML шаблона.');
      return;
    }

    setIsSubmitting(true);
    setErrorMessage(null);
    setSuccessMessage(null);

    try {
      if (formMode === 'create') {
        const createPayload: CreateTemplatePayload = {
          name: normalizedName,
          type: formData.type,
          isActive: formData.isActive,
          content: editorMode === 'simple' ? buildSimpleTemplateHtml(formData.contractText) : formData.content,
          css: editorMode === 'simple' ? '' : formData.css,
        };
        await onCreateTemplate(createPayload);
        setSuccessMessage(`Шаблон «${normalizedName}» создан.`);
      } else if (formMode === 'edit' && editingTemplateId) {
        const updatePayload: UpdateTemplatePayload = {
          name: normalizedName,
          type: formData.type,
          isActive: formData.isActive,
          content: editorMode === 'simple' ? buildSimpleTemplateHtml(formData.contractText) : formData.content,
          css: editorMode === 'simple' ? '' : formData.css,
        };
        await onUpdateTemplate(editingTemplateId, updatePayload);
        setSuccessMessage(`Шаблон «${normalizedName}» обновлен.`);
      }

      closeForm();
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Не удалось сохранить шаблон.';
      setErrorMessage(message);
    } finally {
      setIsSubmitting(false);
    }
  };

  const deleteTemplate = async (template: Template) => {
    const confirmed = window.confirm(`Удалить шаблон «${template.name}»?`);
    if (!confirmed) {
      return;
    }

    setPendingDeleteId(template.id);
    setErrorMessage(null);
    setSuccessMessage(null);

    try {
      await onDeleteTemplate(template.id);
      if (editingTemplateId === template.id) {
        closeForm();
      }
      setSuccessMessage(`Шаблон «${template.name}» удален.`);
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Не удалось удалить шаблон.';
      setErrorMessage(message);
    } finally {
      setPendingDeleteId(null);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 dark:text-slate-100">Шаблоны</h1>
          <p className="text-slate-500 dark:text-slate-400">
            Управление шаблонами договоров: создание, редактирование и удаление.
          </p>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
            Всего: {templates.length}. Активных: {activeTemplatesCount}.
          </p>
        </div>
        <Button icon={<Icons.Plus className="w-4 h-4" />} onClick={startCreate}>
          Создать шаблон
        </Button>
      </div>

      {errorMessage && (
        <Card className="p-4 border-red-200 dark:border-red-900/50 bg-red-50 dark:bg-red-900/20">
          <p className="text-sm text-red-700 dark:text-red-200">{errorMessage}</p>
        </Card>
      )}

      {successMessage && (
        <Card className="p-4 border-green-200 dark:border-green-900/50 bg-green-50 dark:bg-green-900/20">
          <p className="text-sm text-green-700 dark:text-green-200">{successMessage}</p>
        </Card>
      )}

      {formMode && (
        <Card className="p-6">
          <div className="flex items-start justify-between gap-3 mb-4">
            <div>
              <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
                {formMode === 'create' ? 'Новый шаблон' : 'Редактирование шаблона'}
              </h2>
              <p className="text-sm text-slate-500 dark:text-slate-400">
                Встроенный редактор позволяет писать текст договора без HTML и CSS.
              </p>
            </div>
            <Button type="button" variant="ghost" size="sm" onClick={closeForm}>
              Отмена
            </Button>
          </div>

          <form onSubmit={saveTemplate} className="space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              <Input
                label="Название шаблона"
                value={formData.name}
                onChange={(event) => setFormData((prev) => ({ ...prev, name: event.target.value }))}
                placeholder="Например: Договор поставки v2"
              />
              <Select
                label="Тип договора"
                value={formData.type}
                onChange={(event) =>
                  setFormData((prev) => ({
                    ...prev,
                    type: event.target.value as ContractType,
                  }))
                }
                options={TEMPLATE_TYPE_OPTIONS}
              />
              <div className="flex items-end">
                <label className="inline-flex items-center gap-2 text-sm text-slate-700 dark:text-slate-300">
                  <input
                    type="checkbox"
                    checked={formData.isActive}
                    onChange={(event) => setFormData((prev) => ({ ...prev, isActive: event.target.checked }))}
                    className="h-4 w-4 text-blue-600"
                  />
                  Активный шаблон
                </label>
              </div>
            </div>

            <div className="rounded-lg border border-slate-200 dark:border-slate-700 p-3">
              <p className="text-sm font-medium text-slate-800 dark:text-slate-200 mb-2">Режим редактора</p>
              <div className="flex flex-wrap gap-2">
                <Button
                  type="button"
                  size="sm"
                  variant={editorMode === 'simple' ? 'secondary' : 'outline'}
                  onClick={() => setEditorMode('simple')}
                >
                  Встроенный
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant={editorMode === 'advanced' ? 'secondary' : 'outline'}
                  onClick={() => setEditorMode('advanced')}
                >
                  HTML/CSS
                </Button>
              </div>
              <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">
                Версия шаблона при редактировании увеличится автоматически.
              </p>
            </div>

            {editorMode === 'simple' ? (
              <div className="space-y-3">
                <div className="rounded-lg border border-slate-200 dark:border-slate-700 p-3">
                  <p className="text-sm font-medium text-slate-800 dark:text-slate-200 mb-2">Переменные договора</p>
                  <div className="flex flex-wrap gap-2">
                    {availableTemplateTokens.map((token) => (
                      <Button
                        key={token.key}
                        type="button"
                        size="sm"
                        variant="outline"
                        onClick={() => insertToken(token.key)}
                        title={token.label}
                      >
                        {`{{${token.key}}}`}
                      </Button>
                    ))}
                  </div>
                  {availableTemplateTokens.length === 0 && (
                    <p className="text-xs text-amber-700 dark:text-amber-300">Список переменных шаблона не загружен.</p>
                  )}
                  <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">
                    Поддержка форматирования: `#` заголовок, `##` раздел, `-` список.
                  </p>
                </div>

                <div>
                  <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">Текст договора</label>
                  <textarea
                    ref={simpleEditorRef}
                    value={formData.contractText}
                    onChange={(event) => setFormData((prev) => ({ ...prev, contractText: event.target.value }))}
                    rows={16}
                    className="w-full px-3 py-2 border border-slate-300 rounded-md shadow-sm placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 dark:bg-slate-900 dark:text-slate-100 dark:border-slate-700 dark:placeholder-slate-600 text-sm"
                    placeholder="Введите договор обычным текстом..."
                  />
                </div>
              </div>
            ) : (
              <>
                <div>
                  <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">HTML шаблона</label>
                  <textarea
                    value={formData.content}
                    onChange={(event) => setFormData((prev) => ({ ...prev, content: event.target.value }))}
                    rows={10}
                    className="w-full px-3 py-2 border border-slate-300 rounded-md shadow-sm placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 dark:bg-slate-900 dark:text-slate-100 dark:border-slate-700 dark:placeholder-slate-600 font-mono text-sm"
                    placeholder="<div class='document-page'>...</div>"
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">CSS шаблона</label>
                  <textarea
                    value={formData.css}
                    onChange={(event) => setFormData((prev) => ({ ...prev, css: event.target.value }))}
                    rows={8}
                    className="w-full px-3 py-2 border border-slate-300 rounded-md shadow-sm placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 dark:bg-slate-900 dark:text-slate-100 dark:border-slate-700 dark:placeholder-slate-600 font-mono text-sm"
                    placeholder=".document-page { font-family: 'Times New Roman', serif; }"
                  />
                </div>
              </>
            )}

            <div className="flex justify-end">
              <Button type="submit" icon={<Icons.Save className="w-4 h-4" />} disabled={isSubmitting}>
                {isSubmitting ? 'Сохранение...' : formMode === 'create' ? 'Создать шаблон' : 'Сохранить изменения'}
              </Button>
            </div>
          </form>
        </Card>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {templates.map((template) => (
          <Card key={template.id} className="p-6 flex flex-col group hover:shadow-md transition-shadow dark:hover:border-blue-700/50">
            <div className="flex items-start justify-between mb-4">
              <div className="p-3 bg-blue-50 dark:bg-blue-900/20 text-blue-600 dark:text-blue-400 rounded-lg group-hover:bg-blue-100 dark:group-hover:bg-blue-900/40 transition-colors">
                <Icons.FileText className="w-6 h-6" />
              </div>
              <div className="flex items-center gap-2">
                <Badge type="info">v{template.version}</Badge>
                <Badge type={template.isActive ? 'success' : 'neutral'}>{template.isActive ? 'Активен' : 'Отключен'}</Badge>
              </div>
            </div>

            <h3 className="text-lg font-semibold text-slate-900 dark:text-slate-100 mb-1">{template.name}</h3>
            <p className="text-sm text-slate-500 dark:text-slate-400 mb-4">{template.type}</p>

            <div className="mt-auto pt-4 border-t border-slate-100 dark:border-slate-800 flex items-center justify-between text-sm">
              <span className="text-slate-500 dark:text-slate-400">Обновлен: {template.updatedAt}</span>
              <div className="flex gap-2">
                <button
                  type="button"
                  className="p-1 text-slate-400 hover:text-blue-600 dark:hover:text-blue-400"
                  title="Редактировать"
                  onClick={() => startEdit(template)}
                >
                  <Icons.Edit className="w-4 h-4" />
                </button>
                <button
                  type="button"
                  className="p-1 text-slate-400 hover:text-red-600 dark:hover:text-red-400 disabled:opacity-50"
                  title="Удалить"
                  disabled={pendingDeleteId === template.id}
                  onClick={() => deleteTemplate(template)}
                >
                  <Icons.Trash className="w-4 h-4" />
                </button>
              </div>
            </div>
          </Card>
        ))}

        {/* Placeholder for "Add New" visual cue */}
        <button
          type="button"
          onClick={startCreate}
          className="border-2 border-dashed border-slate-200 dark:border-slate-700 rounded-xl p-6 flex flex-col items-center justify-center text-slate-400 dark:text-slate-500 hover:border-blue-400 dark:hover:border-blue-500 hover:text-blue-500 dark:hover:text-blue-400 transition-colors group h-full min-h-[200px]"
        >
          <div className="p-3 rounded-full bg-slate-50 dark:bg-slate-800 group-hover:bg-blue-50 dark:group-hover:bg-slate-700 mb-3">
            <Icons.Plus className="w-6 h-6" />
          </div>
          <span className="font-medium">Создать новый шаблон</span>
        </button>
      </div>
    </div>
  );
};
