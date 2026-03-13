import { test, expect } from '@playwright/test';

test('dashboard shell renders', async ({ page }) => {
  await page.goto('/dashboard');
  await expect(page.locator('body')).toBeVisible();
});
