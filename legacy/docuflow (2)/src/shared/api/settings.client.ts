import { AppSettings } from '../../../types';
import { requestJson } from './http';

export const settingsClient = {
  getSettings: () => requestJson<AppSettings>('/settings'),

  updateSettings: (payload: Partial<AppSettings>) =>
    requestJson<AppSettings>('/settings', {
      method: 'PUT',
      body: JSON.stringify(payload),
    }),
};
