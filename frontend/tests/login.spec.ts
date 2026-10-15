import { expect, test, type Page } from "@playwright/test";

// Runs only against a backend in Keycloak mode wired to scripts/stub_oidc.py (TEST-ONLY IdP):
//   SEPEHR_E2E_OIDC=1 PLAYWRIGHT_BASE_URL=http://127.0.0.1:8765 npx playwright test login.spec.ts
test.skip(!process.env.SEPEHR_E2E_OIDC, "requires the stub OIDC provider and a keycloak-mode backend");

async function signIn(page: Page, button: RegExp, user: string) {
  await page.getByRole("button", { name: button }).click();
  await page.locator(`#user-${user}`).click();
  await page.waitForURL((url) => !url.pathname.startsWith("/auth/callback"));
}

test("web console PKCE login, role-aware navigation, logout and API access", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("button", { name: /ورود به کنسول مرکز/ })).toBeVisible();
  await expect(page.locator(".classification-bar")).toHaveText("محرمانه");
  await signIn(page, /ورود به کنسول مرکز/, "supervisor");
  await expect(page.locator(".top-profile")).toContainText("supervisor");
  await expect(page.locator(".top-profile")).toContainText("سرپرست شیفت");
  await expect(page.getByRole("button", { name: /نظارت استثنامحور گشت/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /ارزیابی امنیتی/ })).toHaveCount(0);
  await page.getByRole("button", { name: /نظارت استثنامحور گشت/ }).click();
  await expect(page.getByRole("tab", { name: /تابلوی استثنا/ })).toBeVisible();
  await expect(page.locator(".error-banner")).toHaveCount(0);
  await page.locator(".top-profile").click();
  await page.getByRole("button", { name: /خروج/ }).click();
  await expect(page.getByRole("button", { name: /ورود به کنسول مرکز/ })).toBeVisible();
});

test("auditor reaches the AFTA dossier; tokens never touch web storage", async ({ page }) => {
  await page.goto("/");
  await signIn(page, /ورود به کنسول مرکز/, "auditor");
  await page.getByRole("button", { name: /ارزیابی امنیتی/ }).click();
  await expect(page.getByText("پرونده شواهد ارزیابی امنیتی (افتا)")).toBeVisible();
  await expect(page.getByText("/api/v1/audit/security-dossier").first()).toBeVisible();
  const stored = await page.evaluate(() => JSON.stringify({ ...localStorage }) + JSON.stringify({ ...sessionStorage }));
  expect(stored).not.toContain("eyJ");
});

test("guard login lands only in the field app", async ({ page }) => {
  await page.goto("/");
  await signIn(page, /ورود نگهبان به اپ میدانی/, "guard");
  await expect(page.getByText("ثبت یک‌باره دستگاه")).toBeVisible();
  await expect(page.locator(".sidebar")).toHaveCount(0);
});

test("idle session locks and requires a new login", async ({ page }) => {
  await page.clock.install();
  await page.goto("/");
  await signIn(page, /ورود به کنسول مرکز/, "supervisor");
  await expect(page.locator(".top-profile")).toContainText("supervisor");
  await page.clock.fastForward("20:00");
  await expect(page.getByText(/به‌دلیل عدم فعالیت، نشست قفل شد/)).toBeVisible();
});
