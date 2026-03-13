import { Contract } from '../../../types';
import { requestJson, requestVoid } from './http';
import {
  ContractTemplatePreviewPayload,
  ContractTemplatePreviewResponse,
  CreateContractPayload,
  UpdateContractPayload,
} from './types';

export const contractsClient = {
  createContract: (payload: CreateContractPayload) =>
    requestJson<Contract>('/contracts', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  previewContractTemplate: (payload: ContractTemplatePreviewPayload) =>
    requestJson<ContractTemplatePreviewResponse>('/contracts/preview', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  updateContract: (contractId: string, payload: UpdateContractPayload) =>
    requestJson<Contract>(`/contracts/${contractId}`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    }),

  deleteContract: (contractId: string) =>
    requestVoid(`/contracts/${contractId}`, {
      method: 'DELETE',
    }),
};
