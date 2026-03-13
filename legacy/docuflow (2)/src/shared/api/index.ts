import { bootstrapClient } from './bootstrap.client';
import { contractsClient } from './contracts.client';
import { counterpartiesClient } from './counterparties.client';
import { documentsClient } from './documents.client';
import { invoicesClient } from './invoices.client';
import { settingsClient } from './settings.client';
import { templatesClient } from './templates.client';

export * from './types';

export const api = {
  ...bootstrapClient,
  ...contractsClient,
  ...counterpartiesClient,
  ...invoicesClient,
  ...templatesClient,
  ...settingsClient,
  ...documentsClient,
};
