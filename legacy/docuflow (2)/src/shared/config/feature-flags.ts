export const featureFlags = {
  useApiV2: import.meta.env.VITE_USE_API_V2 === '1' || import.meta.env.VITE_USE_API_V2 === 'true',
  useQueryDataLayer:
    import.meta.env.VITE_USE_QUERY_DATA_LAYER == null ||
    import.meta.env.VITE_USE_QUERY_DATA_LAYER === '1' ||
    import.meta.env.VITE_USE_QUERY_DATA_LAYER === 'true',
  useNewRouter:
    import.meta.env.VITE_USE_NEW_ROUTER == null ||
    import.meta.env.VITE_USE_NEW_ROUTER === '1' ||
    import.meta.env.VITE_USE_NEW_ROUTER === 'true',
};
