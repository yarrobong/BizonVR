import { Invoice } from '../../../types';
import { requestJson, requestVoid } from './http';
import { CreateInvoicePayload, UpdateInvoicePayload } from './types';

export const invoicesClient = {
  createInvoice: (payload: CreateInvoicePayload) =>
    requestJson<Invoice>('/invoices', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  updateInvoice: (invoiceId: string, payload: UpdateInvoicePayload) =>
    requestJson<Invoice>(`/invoices/${invoiceId}`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    }),

  deleteInvoice: (invoiceId: string) =>
    requestVoid(`/invoices/${invoiceId}`, {
      method: 'DELETE',
    }),
};
