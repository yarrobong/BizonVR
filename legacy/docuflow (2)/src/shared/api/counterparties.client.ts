import { Counterparty } from '../../../types';
import { requestJson, requestVoid } from './http';
import { CounterpartyLookupResponse, CreateCounterpartyPayload, UpdateCounterpartyPayload } from './types';

export const counterpartiesClient = {
  createCounterparty: (payload: CreateCounterpartyPayload) =>
    requestJson<Counterparty>('/counterparties', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  updateCounterparty: (counterpartyId: string, payload: UpdateCounterpartyPayload) =>
    requestJson<Counterparty>(`/counterparties/${counterpartyId}`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    }),

  deleteCounterparty: (counterpartyId: string) =>
    requestVoid(`/counterparties/${counterpartyId}`, {
      method: 'DELETE',
    }),

  lookupCounterpartyByInn: (inn: string) =>
    requestJson<CounterpartyLookupResponse>(`/counterparties/lookup?inn=${encodeURIComponent(inn)}`),
};
