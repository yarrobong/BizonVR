import { requestBlob, requestJson } from './http';
import { FileFormat } from './types';

interface GenerateFilePayload {
  html: string;
  css: string;
  fileName: string;
}

interface GeneratePackagePayload {
  format: FileFormat;
  fileName: string;
  files: GenerateFilePayload[];
}

export const documentsClient = {
  generateContractFile: async (format: FileFormat, payload: GenerateFilePayload): Promise<Blob> =>
    requestBlob(`/generate/${format}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  generateDocumentPackage: async (payload: GeneratePackagePayload): Promise<Blob> =>
    requestBlob('/generate/package', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  renderContractV2: async (payload: Record<string, unknown>) =>
    requestJson<{ html: string; css: string; templateId: string; templateName: string; templateVersion?: string }>(
      '/v2/documents/render/contract',
      {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      },
    ),
};
