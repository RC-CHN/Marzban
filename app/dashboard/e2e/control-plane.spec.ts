import { expect, Page, test } from "@playwright/test";

const nodes = [
  { id: 1, name: "node-a", public_host: "203.0.113.10", entry_enabled: true, exit_enabled: true, node_link_port: 12443, public_tls_mode: "ip-ca", status: "connected", version: "1.13.14", sync_enabled: true, last_config_hash: "a", applied_config_hash: "a", last_seen_at: "2026-07-11T01:00:00Z", usage_coefficient: 1 },
  { id: 2, name: "node-b", public_host: "198.51.100.20", entry_enabled: true, exit_enabled: true, node_link_port: 12443, public_tls_mode: "ip-ca", status: "connected", version: "1.13.14", sync_enabled: true, last_config_hash: "b", applied_config_hash: "b", last_seen_at: "2026-07-11T01:00:00Z", usage_coefficient: 1 },
  { id: 3, name: "node-c", public_host: "192.0.2.30", entry_enabled: true, exit_enabled: true, node_link_port: 12443, public_tls_mode: "ip-ca", status: "connecting", version: "1.13.14", sync_enabled: true, last_config_hash: "c2", applied_config_hash: "c1", last_seen_at: "2026-07-11T00:50:00Z", usage_coefficient: 1 },
];

const subscriptions = {
  token: "public-token",
  singbox: "/api/singbox/public-subscription/public-token/sing-box",
  clash: "/api/singbox/public-subscription/public-token/clash",
  v2rayn: "/api/singbox/public-subscription/public-token/v2rayn",
};

const workspace = {
  username: "alice",
  status: "active",
  data_limit: 0,
  used_traffic: 1024,
  expire: 0,
  public_subscription: subscriptions,
  connections: [
    { id: 11, label: "Tokyo direct", protocol: "hysteria2", entry_node_id: 1, entry_node_name: "node-a", exit_node_id: null, exit_node_name: null, enabled: true, sort_order: 100 },
    { id: 12, label: "Tokyo via US", protocol: "tuic", entry_node_id: 1, entry_node_name: "node-a", exit_node_id: 2, exit_node_name: "node-b", enabled: true, sort_order: 200 },
    { id: 13, label: "US via Tokyo", protocol: "anytls", entry_node_id: 2, entry_node_name: "node-b", exit_node_id: 1, exit_node_name: "node-a", enabled: true, sort_order: 300 },
  ],
};

async function mockApi(page: Page) {
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === "/api/admin/token") return route.fulfill({ json: { access_token: "test-token" } });
    if (path === "/api/admin") return route.fulfill({ json: { username: "admin", is_sudo: true } });
    if (path.startsWith("/api/singbox/nodes/") && request.method() === "DELETE") return route.fulfill({ json: {} });
    if (path.endsWith("/protocol-impact")) return route.fulfill({ json: { node_id: Number(path.split("/")[4]), protocols: { hysteria2: 1, tuic: 1, anytls: 1, vmess: 0, vless: 0, trojan: 0, shadowsocks: 0 } } });
    if (path.endsWith("/config")) return route.fulfill({ json: { node_id: Number(path.split("/")[4]), hash: "abc", config: { inbounds: [], outbounds: [] } } });
    if (path.startsWith("/api/singbox/nodes/") && request.method() === "PUT") {
      const node = nodes.find((item) => item.id === Number(path.split("/").pop()));
      Object.assign(node!, request.postDataJSON());
      return route.fulfill({ json: node });
    }
    if (path === "/api/singbox/nodes") return route.fulfill({ json: nodes });
    if (path === "/api/singbox/links") return route.fulfill({ json: [{ id: 21, from_node_id: 1, to_node_id: 2, protocol: "anytls", mtls_enabled: true, enabled: true }] });
    if (path === "/api/singbox/users") return route.fulfill({ json: [{ username: "alice", status: "active", data_limit: 0, used_traffic: 1024, expire: 0, connection_count: 3, public_subscription: subscriptions }] });
    if (path === "/api/singbox/status") return route.fulfill({ json: { public_tls: { insecure: false, mode: "ip-ca" }, node_link_tls: { mtls: true, protocol: "anytls" }, node_upgrade: { enabled: true, target_image: "ghcr.io/example/marzban:v0.10.0" }, nodes: [{ id: 1, heartbeat_stale: false, sync_pending: false }, { id: 2, heartbeat_stale: false, sync_pending: false }, { id: 3, heartbeat_stale: false, sync_pending: true }] } });
    if (path === "/api/singbox/users/alice/connections") return route.fulfill({ json: workspace });
    return route.fulfill({ status: 404, json: { detail: "Not mocked" } });
  });
}

async function login(page: Page) {
  await page.goto("/#/login/");
  await page.getByPlaceholder("Username").fill("admin");
  await page.getByPlaceholder("Password").fill("admin");
  await page.getByRole("button", { name: "Login" }).click();
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
}

test.beforeEach(async ({ page }) => {
  await mockApi(page);
});

test("edits a user's aggregate subscription connections", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name === "mobile");
  await login(page);
  await page.getByRole("link", { name: "Users" }).click();
  await page.getByText("alice", { exact: true }).click();
  await page.getByRole("button", { name: "Add connection" }).click();
  await expect(page.locator("tbody tr")).toHaveCount(4);
  await page.getByRole("tab", { name: "Topology" }).click();
  await page.getByLabel("Connection", { exact: true }).selectOption({ label: "Tokyo via US" });
  await expect(page.locator(".react-flow__viewport")).toBeVisible();
  await expect(page.locator(".react-flow__node")).toHaveCount(4);
  await expect(page.locator(".react-flow__edge")).toHaveCount(3);
  await expect(page.locator(".react-flow__node").filter({ hasText: "ENTRY" })).toBeVisible();
  await expect(page.locator(".react-flow__node").filter({ hasText: "EXIT" })).toBeVisible();
  await expect(page.getByText("anytls:12443 / mTLS")).toBeVisible();
  const canvasBox = await page.locator(".react-flow").boundingBox();
  const entryBox = await page.locator(".react-flow__node").filter({ hasText: "ENTRY" }).boundingBox();
  const exitBox = await page.locator(".react-flow__node").filter({ hasText: "EXIT" }).boundingBox();
  expect(canvasBox).not.toBeNull();
  expect(entryBox!.x).toBeGreaterThanOrEqual(canvasBox!.x);
  expect(exitBox!.x + exitBox!.width).toBeLessThanOrEqual(canvasBox!.x + canvasBox!.width);

  await page.screenshot({ path: "/tmp/marzban-dashboard-desktop.png", fullPage: true });

  await page.getByRole("tab", { name: "Connections" }).click();
  await page.locator('table input[value="Tokyo direct"]').fill("Tokyo primary");
  const update = page.waitForRequest((request) => request.method() === "PUT" && request.url().endsWith("/users/alice/connections"));
  await page.getByRole("button", { name: "Apply changes" }).click();
  const body = (await update).postDataJSON();
  expect(body.connections[0].label).toBe("Tokyo primary");
  expect(body.connections).toHaveLength(4);
});

test("keeps the user workflow usable on mobile", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "mobile");
  await login(page);
  await page.getByRole("button", { name: "Open navigation" }).click();
  await page.getByRole("link", { name: "Users" }).click();
  await page.getByText("alice", { exact: true }).click();
  await expect(page.getByRole("button", { name: "Apply changes" })).toBeVisible();
  await expect(page.locator("body")).not.toHaveCSS("overflow-x", "scroll");
  await page.screenshot({ path: "/tmp/marzban-dashboard-mobile.png", fullPage: true });
});

test("deletes an unused node from the nodes page", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name === "mobile");
  await login(page);
  await page.getByRole("link", { name: "Nodes" }).click();
  await page.getByRole("button", { name: "Delete node-c" }).click();
  await expect(page.getByRole("heading", { name: "Delete node-c" })).toBeVisible();
  const deletion = page.waitForRequest((request) => request.method() === "DELETE" && request.url().endsWith("/singbox/nodes/3"));
  await page.getByRole("button", { name: "Delete node", exact: true }).click();
  await deletion;
  await expect(page.getByText("Node deleted")).toBeVisible();
});

test("opens and updates the shared ingress profile", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name === "mobile");
  await login(page);
  await page.getByRole("link", { name: "Users" }).click();
  await page.getByText("alice", { exact: true }).click();
  await page.getByRole("tab", { name: "Topology" }).click();
  await page.getByLabel("Connection", { exact: true }).selectOption({ label: "Tokyo via US" });
  await page.getByRole("button", { name: "Configure ingress profile" }).click();
  await expect(page).toHaveURL(/\/nodes\/1\?protocol=tuic/);
  await expect(page.getByText("node-a / tuic", { exact: true })).toBeVisible();
  await page.getByLabel("Ingress port").fill("12002");
  const update = page.waitForRequest((request) => request.method() === "PUT" && request.url().endsWith("/singbox/nodes/1"));
  await page.getByRole("button", { name: "Apply", exact: true }).click();
  expect((await update).postDataJSON().public_ports.tuic).toBe(12002);
});
