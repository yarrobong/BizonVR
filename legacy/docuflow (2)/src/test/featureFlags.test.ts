import { describe, expect, it } from 'vitest';
import { useFeatureFlagsStore } from '../app/store/featureFlags.store';

describe('feature flags store', () => {
  it('has expected keys', () => {
    const flags = useFeatureFlagsStore.getState();
    expect(typeof flags.useApiV2).toBe('boolean');
    expect(typeof flags.useQueryDataLayer).toBe('boolean');
    expect(typeof flags.useNewRouter).toBe('boolean');
  });
});
