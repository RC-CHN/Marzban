import { expect, Page, test } from "@playwright/test";

type LiveIngress = {
  id: number;
  node_id: number;
  listen_port: number;
  enabled: boolean;
  oper_state: string;
};

type LiveWorkspace = {
  topology_revision: number;
  ingresses: LiveIngress[];
};

async function login(page: Page) {
  await page.addInitScript(() => localStorage.setItem("marzbanLanguage", "en"));
  await page.goto("#/login/");
  await page.locator('input[name="username"]').fill(process.env.E2E_ADMIN_USERNAME || "admin");
  await page.locator('input[name="password"]').fill(process.env.E2E_ADMIN_PASSWORD || "admin");
  await page.locator('button[type="submit"]').click();
  await expect(page.getByRole("heading", { name: "Overview", exact: true })).toBeVisible();
}

async function authenticatedJson<T>(page: Page, path: string): Promise<T> {
  return page.evaluate(async (requestPath) => {
    const response = await fetch(requestPath, {
      headers: { Authorization: `Bearer ${localStorage.getItem("token")}` },
    });
    if (!response.ok) throw new Error(`${requestPath} returned HTTP ${response.status}`);
    return response.json();
  }, path);
}

async function graphNodePoint(page: Page, id: string) {
  return page.getByTestId("network-canvas").evaluate((element, nodeId) => {
    const chart = (element as HTMLDivElement & { __networkChart: any }).__networkChart;
    const series = chart.getModel().getSeriesByIndex(0);
    const data = series.getData();
    let index = -1;
    for (let item = 0; item < data.count(); item += 1) {
      if (data.getId(item) === nodeId) index = item;
    }
    if (index < 0) throw new Error(`Graph node ${nodeId} was not found`);
    const point = series.coordinateSystem.dataToPoint(data.getItemLayout(index));
    const bounds = element.getBoundingClientRect();
    return { x: bounds.left + point[0], y: bounds.top + point[1] };
  }, id);
}

async function selectIngress(page: Page, ingressId: number) {
  const point = await graphNodePoint(page, `ingress-${ingressId}`);
  await page.mouse.click(point.x, point.y, { button: "right" });
  await expect(page.getByText("Ingress service", { exact: true })).toBeVisible();
}

async function saveIngressPort(page: Page, ingressId: number, port: number) {
  await selectIngress(page, ingressId);
  await page.getByLabel("Listen port").fill(String(port));
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "Save topology" })).toBeVisible();
  const applied = page.waitForResponse((response) => (
    response.request().method() === "POST"
      && response.url().endsWith("/api/singbox/network/drafts/apply")
  ));
  await page.getByRole("button", { name: "Save revision" }).click();
  expect((await applied).ok()).toBeTruthy();
}

async function waitForConvergence(page: Page, ingressId: number, port: number) {
  await expect.poll(async () => {
    const workspace = await authenticatedJson<LiveWorkspace>(page, "/api/singbox/network");
    const ingress = workspace.ingresses.find((item) => item.id === ingressId);
    return ingress && { port: ingress.listen_port, state: ingress.oper_state };
  }, { timeout: 180_000, intervals: [1_000, 2_000, 5_000] }).toEqual({ port, state: "up" });

  await expect.poll(async () => {
    const nodes = await authenticatedJson<Array<{
      status: string;
      last_config_hash: string | null;
      applied_config_hash: string | null;
    }>>(page, "/api/singbox/nodes");
    return nodes.every((node) => (
      node.status === "connected"
        && Boolean(node.last_config_hash)
        && node.last_config_hash === node.applied_config_hash
    ));
  }, { timeout: 180_000, intervals: [1_000, 2_000, 5_000] }).toBe(true);

  await expect.poll(async () => {
    const status = await authenticatedJson<{ routing: { status: string } }>(
      page,
      "/api/singbox/status",
    );
    return status.routing.status;
  }, { timeout: 180_000, intervals: [1_000, 2_000, 5_000] }).toBe("active");
}

test("saves a real topology revision and converges the node listener", async ({ page }) => {
  await login(page);
  await page.getByRole("link", { name: "Network" }).click();
  await expect(page.getByTestId("network-canvas")).toBeVisible();
  await page.waitForTimeout(1_100);

  await expect.poll(async () => {
    const workspace = await authenticatedJson<LiveWorkspace>(page, "/api/singbox/network");
    return workspace.ingresses.filter((item) => item.enabled && item.oper_state === "up").length;
  }, { timeout: 180_000, intervals: [1_000, 2_000, 5_000] }).toBeGreaterThan(0);
  const before = await authenticatedJson<LiveWorkspace>(page, "/api/singbox/network");
  const ingress = before.ingresses.find((item) => item.enabled && item.oper_state === "up");
  expect(ingress).toBeTruthy();
  const testPort = ingress!.listen_port + 5_000;

  await saveIngressPort(page, ingress!.id, testPort);
  await waitForConvergence(page, ingress!.id, testPort);
  const changed = await authenticatedJson<LiveWorkspace>(page, "/api/singbox/network");
  expect(changed.topology_revision).toBeGreaterThan(before.topology_revision);

  await saveIngressPort(page, ingress!.id, ingress!.listen_port);
  await waitForConvergence(page, ingress!.id, ingress!.listen_port);
});

test("renders the categorized resource editor over HTTPS", async ({ page }) => {
  await login(page);
  await page.getByRole("link", { name: "Network" }).click();
  await page.getByRole("tab", { name: "Resources" }).click();
  await page.getByRole("tab", { name: "Ingresses" }).click();
  await page.locator("tbody tr").first().click();
  await expect(page.getByText("Ingress service", { exact: true })).toBeVisible();
  await expect(page.getByRole("tab", { name: "General", exact: true })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByLabel("Certificate path", { exact: true })).not.toBeVisible();
  await page.getByRole("tab", { name: "TLS", exact: true }).click();
  await expect(page.getByLabel("Certificate path", { exact: true })).toBeVisible();
  await page.screenshot({ path: "/tmp/marzban-network-resources-live.png", fullPage: true });
  await page.getByRole("button", { name: "Language" }).click();
  await page.getByRole("menuitem", { name: "简体中文" }).click();
  await expect(page.getByRole("heading", { name: "网络", exact: true })).toBeVisible();
  await expect(page.getByRole("tab", { name: "TLS 与证书", exact: true })).toBeVisible();
  await page.screenshot({ path: "/tmp/marzban-network-resources-live-zh.png", fullPage: true });
});
