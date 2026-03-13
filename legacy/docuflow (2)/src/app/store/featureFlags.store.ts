import { create } from 'zustand';

interface FeatureFlagsState {
  useApiV2: boolean;
  useQueryDataLayer: boolean;
  useNewRouter: boolean;
}

const envBool = (value: string | undefined, fallback = false) => {
  if (!value) {
    return fallback;
  }
  return value === '1' || value.toLowerCase() === 'true';
};

export const useFeatureFlagsStore = create<FeatureFlagsState>(() => ({
  useApiV2: envBool(import.meta.env.VITE_USE_API_V2, false),
  useQueryDataLayer: envBool(import.meta.env.VITE_USE_QUERY_DATA_LAYER, true),
  useNewRouter: envBool(import.meta.env.VITE_USE_NEW_ROUTER, true),
}));
