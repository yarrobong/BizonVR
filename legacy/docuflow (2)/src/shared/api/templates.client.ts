import { Template } from '../../../types';
import { requestJson, requestVoid } from './http';
import { CreateTemplatePayload, UpdateTemplatePayload } from './types';

export const templatesClient = {
  createTemplate: (payload: CreateTemplatePayload) =>
    requestJson<Template>('/templates', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  updateTemplate: (templateId: string, payload: UpdateTemplatePayload) =>
    requestJson<Template>(`/templates/${templateId}`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    }),

  deleteTemplate: (templateId: string) =>
    requestVoid(`/templates/${templateId}`, {
      method: 'DELETE',
    }),
};
