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
    { id: 11, label: "Tokyo direct", protocol: "hysteria2", entry_node_id: 1, entry_node_name: "node-a", exit_node_id: null, exit_node_name: null, ingress_service_id: 101, egress_service_id: 201, routing_policy_id: 301, enabled: true, sort_order: 100 },
    { id: 12, label: "Tokyo via US", protocol: "tuic", entry_node_id: 1, entry_node_name: "node-a", exit_node_id: 2, exit_node_name: "node-b", ingress_service_id: 102, egress_service_id: 202, routing_policy_id: 301, enabled: true, sort_order: 200 },
    { id: 13, label: "US via Tokyo", protocol: "anytls", entry_node_id: 2, entry_node_name: "node-b", exit_node_id: 1, exit_node_name: "node-a", ingress_service_id: 103, egress_service_id: 201, routing_policy_id: 301, enabled: true, sort_order: 300 },
  ],
};

let topologyRevision = 4;
const network = {
  topology_revision: topologyRevision,
  nodes,
  addresses: nodes.map((node) => ({ id: 500 + node.id, node_id: node.id, address: node.public_host, kind: "public", is_primary: true, enabled: true })),
  ingresses: [
    { id: 101, node_id: 1, advertised_address_id: 501, node_name: "node-a", address: nodes[0].public_host, name: "Tokyo Hysteria2", protocol: "hysteria2", listen_port: 11001, enabled: true, tls_mode: "ip-ca", tls_profile: {}, protocol_profile: {}, oper_state: "up", message: "hysteria2 listener is active on port 11001" },
    { id: 102, node_id: 1, advertised_address_id: 501, node_name: "node-a", address: nodes[0].public_host, name: "Tokyo TUIC", protocol: "tuic", listen_port: 11002, enabled: true, tls_mode: "ip-ca", tls_profile: {}, protocol_profile: {}, oper_state: "up", message: "tuic listener is active on port 11002" },
    { id: 103, node_id: 2, advertised_address_id: 502, node_name: "node-b", address: nodes[1].public_host, name: "US AnyTLS", protocol: "anytls", listen_port: 11001, enabled: true, tls_mode: "ip-ca", tls_profile: {}, protocol_profile: {}, oper_state: "down", message: "anytls listener is not active on port 11001" },
  ],
  egresses: [
    { id: 201, node_id: 1, node_name: "node-a", name: "Direct @ node-a", kind: "direct", enabled: true, settings: {} },
    { id: 202, node_id: 2, node_name: "node-b", name: "Direct @ node-b", kind: "direct", enabled: true, settings: {} },
    { id: 203, node_id: 3, node_name: "node-c", name: "Direct @ node-c", kind: "direct", enabled: true, settings: {} },
  ],
  adjacencies: [
    { id: 401, node_a_id: 1, node_b_id: 3, name: "node-a <-> node-c", enabled: true, directions: [
      { id: 411, from_node_id: 1, to_node_id: 3, enabled: true, transport: "anytls", listen_port: 21001, admin_cost: 40, settings: {}, oper_state: "up", rtt_ms: 28 },
      { id: 412, from_node_id: 3, to_node_id: 1, enabled: true, transport: "anytls", listen_port: 21002, admin_cost: 40, settings: {}, oper_state: "up", rtt_ms: 29 },
    ] },
    { id: 402, node_a_id: 2, node_b_id: 3, name: "node-b <-> node-c", enabled: true, directions: [
      { id: 413, from_node_id: 3, to_node_id: 2, enabled: true, transport: "hysteria2", listen_port: 21003, admin_cost: 60, settings: {}, oper_state: "up", rtt_ms: 45 },
      { id: 414, from_node_id: 2, to_node_id: 3, enabled: true, transport: "hysteria2", listen_port: 21004, admin_cost: 60, settings: {}, oper_state: "up", rtt_ms: 44 },
    ] },
  ],
  routing_policies: [{ id: 301, name: "Default", metric_mode: "admin_only", max_hops: 8, allow_degraded: false, failover: true, required_node_ids: [], avoided_node_ids: [] }],
};

const route12 = {
  connection_id: 12, status: "reachable", topology_revision: 4, route_revision: 7,
  total_cost: 100, hop_count: 2,
  reason: "Selected lowest cost path (100); ties prefer fewer hops then stable edge IDs",
  hops: [
    { position: 0, adjacency_direction_id: 411, from_node_id: 1, from_node_name: "node-a", to_node_id: 3, to_node_name: "node-c", transport: "anytls", admin_cost: 40 },
    { position: 1, adjacency_direction_id: 413, from_node_id: 3, from_node_name: "node-c", to_node_id: 2, to_node_name: "node-b", transport: "hysteria2", admin_cost: 60 },
  ],
  candidates: [{ node_ids: [1, 3, 2], node_names: ["node-a", "node-c", "node-b"], adjacency_direction_ids: [411, 413], total_cost: 100, hop_count: 2, selected: true }],
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
    if (path === "/api/singbox/network" && request.method() === "GET") return route.fulfill({ json: { ...network, topology_revision: topologyRevision } });
    if (path === "/api/singbox/network/drafts/validate") return route.fulfill({ json: { valid: true, issues: [], affected_connections: 3, reachable_connections: 3 } });
    if (path === "/api/singbox/network/drafts/apply") { topologyRevision += 1; return route.fulfill({ json: { topology_revision: topologyRevision, route_revision: 8, status: "staged", reachable_connections: 3, degraded_connections: 0 } }); }
    if (path === "/api/singbox/connections/12/route") return route.fulfill({ json: route12 });
    if (/\/api\/singbox\/connections\/\d+\/route/.test(path)) return route.fulfill({ json: { ...route12, connection_id: Number(path.split("/")[4]), hops: [], hop_count: 0, total_cost: 0, candidates: [] } });
    if (path === "/api/singbox/links") return route.fulfill({ json: [{ id: 21, from_node_id: 1, to_node_id: 2, protocol: "anytls", mtls_enabled: true, enabled: true }] });
    if (path === "/api/singbox/users") return route.fulfill({ json: [{ username: "alice", status: "active", data_limit: 0, used_traffic: 1024, expire: 0, connection_count: 3, public_subscription: subscriptions }] });
    if (path === "/api/singbox/status") return route.fulfill({ json: { public_tls: { insecure: false, mode: "ip-ca" }, node_link_tls: { mtls: true, protocol: "anytls" }, node_upgrade: { enabled: true, target_image: "ghcr.io/example/marzban:v0.10.0" }, nodes: [{ id: 1, heartbeat_stale: false, sync_pending: false }, { id: 2, heartbeat_stale: false, sync_pending: false }, { id: 3, heartbeat_stale: false, sync_pending: true }] } });
    if (path === "/api/singbox/users/alice/connections") return route.fulfill({ json: workspace });
    return route.fulfill({ status: 404, json: { detail: "Not mocked" } });
  });
}

async function login(page: Page, language: "en" | "zh" | null = "en") {
  if (language) await page.addInitScript((value) => localStorage.setItem("marzbanLanguage", value), language);
  await page.goto("/#/login/");
  await page.locator('input[name="username"]').fill("admin");
  await page.locator('input[name="password"]').fill("admin");
  await page.locator('button[type="submit"]').click();
  await expect(page.getByRole("heading", { name: language === "en" ? "Overview" : "概览", exact: true })).toBeVisible();
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
    const point = series.coordinateSystem.dataToPoint(data.getItemLayout(index));
    const bounds = element.getBoundingClientRect();
    return { x: bounds.left + point[0], y: bounds.top + point[1] };
  }, id);
}

async function graphEdgePoint(page: Page, id: string) {
  return page.getByTestId("network-canvas").evaluate((element, edgeId) => {
    const chart = (element as HTMLDivElement & { __networkChart: any }).__networkChart;
    const series = chart.getModel().getSeriesByIndex(0);
    const data = series.getEdgeData();
    let index = -1;
    for (let item = 0; item < data.count(); item += 1) {
      if (data.getId(item) === edgeId) index = item;
    }
    const [source, target, control] = data.getItemLayout(index);
    const point = control
      ? [0.25 * source[0] + 0.5 * control[0] + 0.25 * target[0], 0.25 * source[1] + 0.5 * control[1] + 0.25 * target[1]]
      : [(source[0] + target[0]) / 2, (source[1] + target[1]) / 2];
    const [x, y] = series.coordinateSystem.dataToPoint(point);
    const bounds = element.getBoundingClientRect();
    return { x: bounds.left + x, y: bounds.top + y };
  }, id);
}

async function graphView(page: Page) {
  return page.getByTestId("network-canvas").evaluate((element) => {
    const chart = (element as HTMLDivElement & { __networkChart: any }).__networkChart;
    const series = chart.getModel().getSeriesByIndex(0);
    const view = chart.getViewOfSeriesModel(series);
    return view._mainGroup.getLocalTransform().map((value: number) => Math.round(value * 1000) / 1000);
  });
}

test.beforeEach(async ({ page }) => {
  await mockApi(page);
});

test("defaults to Chinese and switches the control plane to English", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name === "mobile");
  await login(page, null);
  await expect(page.getByRole("link", { name: "网络", exact: true })).toBeVisible();
  await page.getByRole("link", { name: "网络", exact: true }).click();
  await expect(page.getByRole("heading", { name: "网络", exact: true })).toBeVisible();
  await page.getByRole("tab", { name: "资源列表", exact: true }).click();
  await expect(page.getByText("资源表和拓扑图编辑同一份草稿，只有点击保存才会下发。")).toBeVisible();
  await page.screenshot({ path: "/tmp/marzban-network-resources-zh.png", fullPage: true });
  await page.getByRole("button", { name: "语言" }).click();
  await page.getByRole("menuitem", { name: "English" }).click();
  await expect(page.getByRole("heading", { name: "Network", exact: true })).toBeVisible();
  await expect(page.getByRole("tab", { name: "Topology", exact: true })).toBeVisible();
  expect(await page.evaluate(() => localStorage.getItem("marzbanLanguage"))).toBe("en");
});

test("edits a user's aggregate subscription connections", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name === "mobile");
  await login(page);
  await page.getByRole("link", { name: "Users" }).click();
  await page.getByText("alice", { exact: true }).click();
  await page.getByRole("button", { name: "Add Connection" }).click();
  await expect(page.locator("tbody tr")).toHaveCount(4);
  await page.getByRole("tab", { name: "Topology" }).click();
  await page.getByLabel("Connection", { exact: true }).selectOption({ label: "Tokyo via US" });
  await expect(page.locator(".react-flow__viewport")).toBeVisible();
  await expect(page.locator(".react-flow__node")).toHaveCount(7);
  await expect(page.locator(".react-flow__edge")).toHaveCount(6);
  await expect(page.locator(".react-flow__node").filter({ hasText: "ENTRY" })).toBeVisible();
  await expect(page.locator(".react-flow__node").filter({ hasText: "EXIT" })).toBeVisible();
  await expect(page.getByText("anytls / cost 40")).toBeVisible();
  await expect(page.getByText("hysteria2 / cost 60")).toBeVisible();
  await expect(page.getByText("node-a → node-c → node-b · cost 100")).toBeVisible();
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

test("edits and validates the global network graph", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name === "mobile");
  await login(page);
  await page.getByRole("link", { name: "Network" }).click();
  await expect(page.getByTestId("network-canvas")).toBeVisible();
  await expect(page.getByTestId("network-canvas")).toHaveAttribute("data-node-count", "9");
  await page.waitForTimeout(1100);
  await expect(page.getByRole("button", { name: "Save", exact: true })).toBeDisabled();

  const serverPoint = await graphNodePoint(page, "server-1");
  await page.mouse.move(serverPoint.x, serverPoint.y);
  await page.mouse.down();
  await page.mouse.move(serverPoint.x + 45, serverPoint.y + 25, { steps: 8 });
  await page.mouse.up();
  await expect(page.getByRole("button", { name: "Save", exact: true })).toBeDisabled();

  const canvasBox = await page.getByTestId("network-canvas").boundingBox();
  const viewBeforeRightDrag = await graphView(page);
  await page.mouse.move(canvasBox!.x + 25, canvasBox!.y + 25);
  await page.mouse.down({ button: "right" });
  await page.mouse.move(canvasBox!.x + 85, canvasBox!.y + 65, { steps: 8 });
  await page.mouse.up({ button: "right" });
  const viewAfterRightDrag = await graphView(page);
  expect(viewAfterRightDrag).toEqual(viewBeforeRightDrag);
  await expect(page.getByRole("button", { name: "Add ingress" })).not.toBeVisible();

  await page.mouse.move(canvasBox!.x + 25, canvasBox!.y + 25);
  await page.mouse.down();
  await page.mouse.move(canvasBox!.x + 85, canvasBox!.y + 65, { steps: 8 });
  await page.mouse.up();
  expect(await graphView(page)).not.toEqual(viewAfterRightDrag);
  await expect(page.getByRole("button", { name: "Save", exact: true })).toBeDisabled();

  await page.getByRole("button", { name: "Connect nodes" }).click();
  await expect(page.getByTestId("network-canvas")).toHaveAttribute("data-canvas-tool", "connect");
  const ingressPoint = await graphNodePoint(page, "ingress-101");
  const invalidPoint = await graphNodePoint(page, "ingress-102");
  await page.mouse.move(ingressPoint.x, ingressPoint.y);
  await page.mouse.down();
  await page.mouse.move(invalidPoint.x, invalidPoint.y, { steps: 10 });
  await page.mouse.up();
  await expect(page.getByRole("button", { name: "Save", exact: true })).toBeDisabled();

  const conflictingServerPoint = await graphNodePoint(page, "server-2");
  const ingressPointForConflict = await graphNodePoint(page, "ingress-101");
  await page.mouse.move(ingressPointForConflict.x, ingressPointForConflict.y);
  await page.mouse.down();
  await page.mouse.move(conflictingServerPoint.x, conflictingServerPoint.y, { steps: 12 });
  await page.mouse.up();
  await expect(page.getByRole("button", { name: "Save", exact: true })).toBeDisabled();

  const serverPointA = await graphNodePoint(page, "server-1");
  const serverPointC = await graphNodePoint(page, "server-3");
  await page.mouse.move(serverPointA.x, serverPointA.y);
  await page.mouse.down();
  await page.mouse.move(serverPointC.x, serverPointC.y, { steps: 12 });
  await page.mouse.up();
  await expect(page.getByRole("button", { name: "Save", exact: true })).toBeDisabled();

  const targetPoint = await graphNodePoint(page, "server-3");
  const ingressPointForConnection = await graphNodePoint(page, "ingress-101");
  await page.mouse.move(ingressPointForConnection.x, ingressPointForConnection.y);
  await page.mouse.down();
  await expect(page.getByText("Link from hysteria2:11001")).toBeVisible();
  await page.mouse.move(targetPoint.x, targetPoint.y, { steps: 16 });
  await page.mouse.up();
  await expect(page.getByRole("button", { name: "Save", exact: true })).toBeEnabled();

  await page.getByRole("button", { name: "Select and move" }).click();
  await page.waitForTimeout(350);
  const adjacencyPoint = await graphEdgePoint(page, "adjacency-401");
  await page.mouse.click(adjacencyPoint.x, adjacencyPoint.y, { button: "right" });
  await expect(page.getByRole("paragraph").filter({ hasText: "node-a <-> node-c" })).toBeVisible();
  await page.getByRole("tab", { name: "node-a → node-c", exact: true }).click();
  await page.getByLabel("Cost").first().fill("25");
  await page.getByLabel("Idle check interval").first().fill("12s");
  const validation = page.waitForRequest((request) => request.url().endsWith("/network/drafts/validate"));
  await page.getByRole("button", { name: "Save", exact: true }).click();
  const draft = (await validation).postDataJSON();
  expect(draft.ingresses[0].node_id).toBe(3);
  expect(draft.adjacencies[0].directions[0].admin_cost).toBe(25);
  expect(draft.adjacencies[0].directions[0].settings.idle_session_check_interval).toBe("12s");
  await expect(page.getByRole("dialog", { name: "Save topology" })).toBeVisible();
  const apply = page.waitForRequest((request) => request.url().endsWith("/network/drafts/apply"));
  await page.getByRole("button", { name: "Save revision" }).click();
  await apply;
  await expect(page.getByText(/Topology r5, route r8 staged/)).toBeVisible();
});

test("adds an unbound service from the canvas menu", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name === "mobile");
  await login(page);
  await page.getByRole("link", { name: "Network" }).click();
  await page.getByTestId("network-canvas").click({ button: "right", position: { x: 20, y: 20 } });
  await expect(page.getByRole("button", { name: "Add ingress" })).toBeVisible();
  await page.getByTestId("network-canvas").click({ position: { x: 260, y: 20 } });
  await expect(page.getByRole("button", { name: "Add ingress" })).not.toBeVisible();
  await page.getByTestId("network-canvas").click({ button: "right", position: { x: 20, y: 20 } });
  await page.getByRole("button", { name: "Add ingress" }).click();
  await expect(page.getByTestId("network-canvas")).toHaveAttribute("data-node-count", "10");
  await expect(page.getByLabel("Name")).toHaveValue("Ingress 4");
  await expect(page.getByRole("button", { name: "Save", exact: true })).toBeEnabled();
});

test("edits network resources without using the topology canvas", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name === "mobile");
  await login(page);
  await page.getByRole("link", { name: "Network" }).click();
  await page.getByRole("tab", { name: "Resources" }).click();
  await expect(page.getByTestId("network-canvas")).not.toBeVisible();

  await page.getByRole("tab", { name: "Ingresses" }).click();
  await page.getByRole("button", { name: "Edit ingress Tokyo Hysteria2" }).click();
  await expect(page.getByRole("tab", { name: "General", exact: true })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByLabel("Certificate path", { exact: true })).not.toBeVisible();
  await page.getByLabel("Name").fill("Form ingress");
  await page.getByLabel("Server", { exact: true }).selectOption("3");
  await page.getByLabel("Advertised address").selectOption("503");
  await page.getByLabel("Listen port").fill("12001");
  await page.screenshot({ path: "/tmp/marzban-network-resources-desktop.png", fullPage: true });
  await page.getByRole("tab", { name: "TLS", exact: true }).click();
  await expect(page.getByLabel("Certificate path", { exact: true })).toBeVisible();
  await page.getByLabel("TLS mode").selectOption("ip-ca");

  await page.getByRole("tab", { name: "Egresses" }).click();
  await page.getByRole("button", { name: "Edit egress Direct @ node-a" }).click();
  await page.getByLabel("Name").fill("Form egress");
  await page.getByLabel("Server", { exact: true }).selectOption("3");

  await page.getByRole("tab", { name: "Adjacencies" }).click();
  await page.getByRole("button", { name: "Add adjacency" }).click();
  await page.getByLabel("Name").fill("Form adjacency");
  await expect(page.getByLabel("Cost")).not.toBeVisible();
  await page.getByRole("tab").filter({ hasText: "→" }).first().click();
  await page.getByLabel("Cost").first().fill("25");
  await page.screenshot({ path: "/tmp/marzban-network-adjacency-desktop.png", fullPage: true });

  await page.getByRole("tab", { name: "Policies" }).click();
  await page.getByRole("button", { name: "Edit policy Default" }).click();
  await page.getByLabel("Maximum hops").fill("6");

  const validation = page.waitForRequest((request) => request.url().endsWith("/network/drafts/validate"));
  await page.getByRole("button", { name: "Save", exact: true }).click();
  const draft = (await validation).postDataJSON();
  expect(draft.ingresses[0]).toMatchObject({ name: "Form ingress", node_id: 3, advertised_address_id: 503, listen_port: 12001, tls_mode: "ip-ca" });
  expect(draft.egresses[0]).toMatchObject({ name: "Form egress", node_id: 3 });
  expect(draft.adjacencies).toHaveLength(3);
  expect(draft.adjacencies[2].name).toBe("Form adjacency");
  expect(draft.adjacencies[2].directions[0].admin_cost).toBe(25);
  expect(draft.routing_policies[0].max_hops).toBe(6);
  await expect(page.getByRole("dialog", { name: "Save topology" })).toBeVisible();
});

test("keeps the categorized resource editor usable on mobile", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "mobile");
  await login(page);
  await page.getByRole("button", { name: "Open navigation" }).click();
  await page.getByRole("link", { name: "Network" }).click();
  await page.getByRole("tab", { name: "Resources" }).click();
  await page.getByRole("tab", { name: "Ingresses" }).click();
  await page.getByRole("button", { name: "Edit ingress Tokyo Hysteria2" }).click();
  await expect(page.getByRole("tab", { name: "General", exact: true })).toBeVisible();
  await expect(page.getByLabel("Certificate path", { exact: true })).not.toBeVisible();
  await page.getByRole("tab", { name: "TLS", exact: true }).click();
  await expect(page.getByLabel("Certificate path", { exact: true })).toBeVisible();
  await expect(page.locator("body")).not.toHaveCSS("overflow-x", "scroll");
  await page.screenshot({ path: "/tmp/marzban-network-resources-mobile.png", fullPage: true });
});
