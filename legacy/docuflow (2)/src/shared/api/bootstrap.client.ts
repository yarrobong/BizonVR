import { requestJson } from './http';
import { BootstrapResponse } from './types';

export const bootstrapClient = {
  getBootstrap: () => requestJson<BootstrapResponse>('/bootstrap'),
  getBootstrapV1: () => requestJson<BootstrapResponse>('/v1/bootstrap'),
};
