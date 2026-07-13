import {
  Alert,
  AlertDescription,
  AlertIcon,
  Badge,
  Box,
  Button,
  ButtonGroup,
  Checkbox,
  FormControl,
  FormHelperText,
  FormLabel,
  Grid,
  HStack,
  IconButton,
  Input,
  Modal,
  ModalBody,
  ModalCloseButton,
  ModalContent,
  ModalFooter,
  ModalHeader,
  ModalOverlay,
  NumberInput,
  NumberInputField,
  Select,
  Skeleton,
  Switch,
  Tab,
  TabList,
  TabPanel,
  TabPanels,
  Tabs,
  Text,
  Tooltip,
  VStack,
  useDisclosure,
  useToast,
} from "@chakra-ui/react";
import {
  ArrowPathIcon,
  CloudArrowUpIcon,
  CursorArrowRaysIcon,
  LinkIcon,
  TrashIcon,
} from "@heroicons/react/24/outline";
import { PageHeader } from "components/AppShell";
import { NetworkResourceTables } from "components/NetworkResourceTables";
import { GraphChart } from "echarts/charts";
import { TooltipComponent } from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { AnyTLSEditor, Hysteria2Editor, TUICEditor } from "pages/NodeDetails";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQuery, useQueryClient } from "react-query";
import { useNavigate } from "react-router-dom";
import { fetch } from "service/http";
import {
  Adjacency,
  AnyTLSSettings,
  DEFAULT_PROTOCOL_SETTINGS,
  EgressService,
  Hysteria2Settings,
  IngressService,
  NetworkDraft,
  NetworkValidation,
  NetworkWorkspace,
  RoutingPolicy,
  SINGBOX_PROTOCOLS,
  SingBoxProtocol,
  SingBoxTLSMode,
  TUICSettings,
} from "types/SingBox";
import { generateErrorMessage, generateSuccessMessage } from "utils/toastHandler";
import Circle from "zrender/lib/graphic/shape/Circle.js";
import Line from "zrender/lib/graphic/shape/Line.js";

echarts.use([GraphChart, TooltipComponent, CanvasRenderer]);

type GraphNodeData = {
  id: string;
  name: string;
  kind: "server" | "ingress" | "egress";
  title: string;
  subtitle: string;
  shortLabel: string;
  meta?: string;
  state?: string;
  objectIndex?: number;
  nodeId?: number;
  value: number;
  symbolSize: number;
  itemStyle: { color: string; borderColor: string; borderWidth: number; shadowBlur: number; shadowColor: string };
};

type GraphEdgeData = {
  id: string;
  source: string;
  target: string;
  name: string;
  kind: "ingress" | "egress" | "adjacency";
  objectIndex: number;
  value: number;
  symbol: ["none" | "arrow", "none" | "arrow"];
  symbolSize: [number, number];
  lineStyle: { color: string; width: number; curveness: number; type?: "solid" | "dashed"; opacity?: number };
};

type Selection =
  | { kind: "server"; nodeId: number }
  | { kind: "ingress" | "egress" | "adjacency" | "policy"; index: number }
  | null;
type CanvasMenu = { x: number; y: number } | null;
type CanvasTool = "select" | "connect";

const ingressNodeId = (item: IngressService, index: number) => `ingress-${item.id ?? `new-${index}`}`;
const egressNodeId = (item: EgressService, index: number) => `egress-${item.id ?? `new-${index}`}`;

const canonicalize = (value: unknown): unknown => {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, item]) => [key, canonicalize(item)]),
    );
  }
  return value;
};

const semanticDraftHash = (draft?: NetworkDraft) => {
  if (!draft) return "";
  const { base_topology_revision: _, ...semantic } = draft;
  return JSON.stringify(canonicalize(semantic));
};

const toDraft = (workspace: NetworkWorkspace): NetworkDraft => ({
  base_topology_revision: workspace.topology_revision,
  ingresses: workspace.ingresses.map(({
    node_name,
    address,
    oper_state,
    observed_at,
    hold_expires_at,
    message,
    ...item
  }) => ({ ...item })),
  egresses: workspace.egresses.map(({ node_name, ...item }) => ({ ...item })),
  adjacencies: workspace.adjacencies.map((item) => ({
    ...item,
    directions: item.directions.map(({ oper_state, rtt_ms, loss_ppm, observed_at, hold_expires_at, message, ...direction }) => ({ ...direction })),
  })),
  routing_policies: workspace.routing_policies.map((item) => ({ ...item })),
});

const directionState = (adjacency: Adjacency) => {
  const states = adjacency.directions.map((item) => item.oper_state || "unknown");
  if (states.includes("down")) return "down";
  if (states.every((state) => state === "up")) return "up";
  return "unknown";
};

const adjacencyOperState = (item: Adjacency, observed?: Adjacency) => {
  if (!item.enabled) return "disabled";
  if (!observed) return item.id ? "unknown" : "new";
  const pendingConfig = item.node_a_id !== observed.node_a_id
    || item.node_b_id !== observed.node_b_id
    || item.enabled !== observed.enabled
    || item.directions.length !== observed.directions.length
    || item.directions.some((direction) => {
      const current = observed.directions.find((candidate) => candidate.id === direction.id);
      return !current
        || direction.enabled !== current.enabled
        || direction.transport !== current.transport
        || direction.listen_port !== current.listen_port
        || direction.admin_cost !== current.admin_cost
        || JSON.stringify(canonicalize(direction.settings)) !== JSON.stringify(canonicalize(current.settings));
    });
  return pendingConfig ? "provisioning" : directionState(observed);
};

const defaultProfile = (protocol: SingBoxProtocol) => {
  if (protocol in DEFAULT_PROTOCOL_SETTINGS) {
    return JSON.parse(JSON.stringify(DEFAULT_PROTOCOL_SETTINGS[protocol as keyof typeof DEFAULT_PROTOCOL_SETTINGS]));
  }
  return {};
};

const nodeStatusColor = (status?: string) => {
  if (status === "connected") return "#16a34a";
  if (status === "error") return "#dc2626";
  if (status === "connecting") return "#d97706";
  return "#64748b";
};

const operStateColor = (state?: string) => {
  if (state === "up") return "#16a34a";
  if (state === "down") return "#dc2626";
  if (state === "provisioning") return "#d97706";
  return "#64748b";
};

const ingressOperState = (item: IngressService, observed?: IngressService) => {
  if (!item.enabled) return "disabled";
  if (!observed) return item.id ? "unknown" : "provisioning";
  const pendingConfig = item.node_id !== observed.node_id
    || item.advertised_address_id !== observed.advertised_address_id
    || item.protocol !== observed.protocol
    || item.listen_port !== observed.listen_port
    || item.tls_mode !== observed.tls_mode
    || JSON.stringify(canonicalize(item.tls_profile)) !== JSON.stringify(canonicalize(observed.tls_profile))
    || JSON.stringify(canonicalize(item.protocol_profile)) !== JSON.stringify(canonicalize(observed.protocol_profile));
  return pendingConfig ? "provisioning" : observed.oper_state || "unknown";
};

const nodeStatusLabel = (status?: string) => ({ connected: "UP", connecting: "WAIT", error: "DOWN", disabled: "OFF" }[status || ""] || "N/A");

const escapeHtml = (value: string) => value
  .replaceAll("&", "&amp;")
  .replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;")
  .replaceAll("'", "&#039;");

type NetworkCanvasProps = {
  nodes: GraphNodeData[];
  edges: GraphEdgeData[];
  layoutVersion: number;
  tool: CanvasTool;
  connectionSourceId?: string;
  onConnect: (sourceId: string, targetId: string) => void;
  canConnect: (sourceId: string, targetId: string) => boolean;
  onConnectionSourceChange: (nodeId?: string) => void;
  onNodeContext: (node: GraphNodeData) => void;
  onEdgeContext: (edge: GraphEdgeData) => void;
  onBlankContext: (x: number, y: number) => void;
  onBlankClick: () => void;
};
type NetworkCanvasElement = HTMLDivElement & { __networkChart?: echarts.ECharts };

const NetworkCanvas = ({ nodes, edges, layoutVersion, tool, connectionSourceId, onConnect, canConnect, onConnectionSourceChange, onNodeContext, onEdgeContext, onBlankContext, onBlankClick }: NetworkCanvasProps) => {
  const elementRef = useRef<NetworkCanvasElement>(null);
  const chartRef = useRef<echarts.ECharts>();
  const [chartReady, setChartReady] = useState(false);
  const callbacksRef = useRef({ tool, connectionSourceId, onConnect, canConnect, onConnectionSourceChange, onNodeContext, onEdgeContext, onBlankContext, onBlankClick });
  const structureRef = useRef("");
  const visualRef = useRef("");
  const layoutVersionRef = useRef(-1);
  callbacksRef.current = { tool, connectionSourceId, onConnect, canConnect, onConnectionSourceChange, onNodeContext, onEdgeContext, onBlankContext, onBlankClick };

  useEffect(() => {
    if (!elementRef.current) return;
    const chart = echarts.init(elementRef.current, undefined, { renderer: "canvas" });
    chartRef.current = chart;
    elementRef.current.__networkChart = chart;
    setChartReady(true);
    let rightDragStart: { x: number; y: number } | undefined;
    let rightDragMoved = false;
    let suppressContextMenuUntil = 0;
    let pendingContextMenu: (() => void) | undefined;
    let panPosition: { x: number; y: number } | undefined;
    let linkSourceId: string | undefined;
    let linkLine: Line | undefined;
    let sourceRing: Circle | undefined;
    let targetRing: Circle | undefined;
    let targetRingNodeId: string | undefined;
    const findNodeAt = (x: number, y: number) => {
      const series = (chart as unknown as { getModel: () => { getSeriesByIndex: (index: number) => any } }).getModel().getSeriesByIndex(0);
      const data = series.getData();
      const coordinateSystem = series.coordinateSystem as { dataToPoint: (point: number[]) => number[] };
      for (let index = 0; index < data.count(); index += 1) {
        const point = coordinateSystem.dataToPoint(data.getItemLayout(index) as number[]);
        const item = data.getRawDataItem(index) as GraphNodeData;
        if (Math.hypot(point[0] - x, point[1] - y) <= item.symbolSize / 2 + 10) {
          return { id: data.getId(index), node: item, point };
        }
      }
      return undefined;
    };
    const clearLinkDrag = () => {
      linkSourceId = undefined;
      targetRingNodeId = undefined;
      if (linkLine) chart.getZr().remove(linkLine as never);
      if (sourceRing) chart.getZr().remove(sourceRing as never);
      if (targetRing) chart.getZr().remove(targetRing as never);
      linkLine = undefined;
      sourceRing = undefined;
      targetRing = undefined;
    };
    chart.on("contextmenu", (params) => {
      params.event?.event?.preventDefault();
      if (rightDragMoved || Date.now() < suppressContextMenuUntil) return;
      const openContextMenu = params.dataType === "node"
        ? () => callbacksRef.current.onNodeContext(params.data as GraphNodeData)
        : params.dataType === "edge"
          ? () => callbacksRef.current.onEdgeContext(params.data as GraphEdgeData)
          : undefined;
      if (!openContextMenu) return;
      if (rightDragStart) pendingContextMenu = openContextMenu;
      else openContextMenu();
    });
    chart.on("click", (params) => {
      if (params.dataType === "node" && callbacksRef.current.tool === "select") {
        callbacksRef.current.onNodeContext(params.data as GraphNodeData);
      } else if (params.dataType === "edge" && callbacksRef.current.tool === "select") {
        callbacksRef.current.onEdgeContext(params.data as GraphEdgeData);
      }
    });
    const zr = chart.getZr();
    zr.on("mousedown", (event) => {
      const nativeEvent = event.event as MouseEvent | undefined;
      if (nativeEvent?.button === 0 && callbacksRef.current.tool === "connect") {
        const source = findNodeAt(event.offsetX, event.offsetY);
        if (!source) return;
        linkSourceId = source.id;
        callbacksRef.current.onConnectionSourceChange(source.id);
        nativeEvent.preventDefault();
        linkLine = new Line({
          silent: true,
          z: 100,
          shape: { x1: source.point[0], y1: source.point[1], x2: event.offsetX, y2: event.offsetY },
          style: { stroke: "#0891b2", lineWidth: 2.5, lineDash: [8, 5], shadowBlur: 8, shadowColor: "rgba(8,145,178,0.3)" },
        });
        zr.add(linkLine as never);
        sourceRing = new Circle({
          silent: true,
          z: 99,
          shape: { cx: source.point[0], cy: source.point[1], r: source.node.symbolSize / 2 + 8 },
          style: { fill: "transparent", stroke: "#f59e0b", lineWidth: 3, shadowBlur: 8, shadowColor: "rgba(245,158,11,0.34)" },
        });
        zr.add(sourceRing as never);
        return;
      }
      if (nativeEvent?.button === 0 && callbacksRef.current.tool === "select" && !findNodeAt(event.offsetX, event.offsetY)) {
        panPosition = { x: event.offsetX, y: event.offsetY };
        nativeEvent.preventDefault();
        return;
      }
      if (nativeEvent?.button !== 2) return;
      rightDragStart = { x: event.offsetX, y: event.offsetY };
      nativeEvent.preventDefault();
    });
    zr.on("mousemove", (event) => {
      if (panPosition) {
        chart.dispatchAction({
          type: "graphRoam",
          seriesIndex: 0,
          dx: event.offsetX - panPosition.x,
          dy: event.offsetY - panPosition.y,
        });
        panPosition = { x: event.offsetX, y: event.offsetY };
      }
      if (linkLine && linkSourceId) {
        linkLine.setShape({ x2: event.offsetX, y2: event.offsetY });
        const target = findNodeAt(event.offsetX, event.offsetY);
        if (target?.id !== targetRingNodeId) {
          if (targetRing) zr.remove(targetRing as never);
          targetRing = undefined;
          targetRingNodeId = target?.id;
          if (target) {
            const valid = callbacksRef.current.canConnect(linkSourceId, target.id);
            targetRing = new Circle({
              silent: true,
              z: 99,
              shape: { cx: target.point[0], cy: target.point[1], r: target.node.symbolSize / 2 + 8 },
              style: { fill: "transparent", stroke: valid ? "#22c55e" : "#ef4444", lineWidth: 3, shadowBlur: 8, shadowColor: valid ? "rgba(34,197,94,0.32)" : "rgba(239,68,68,0.28)" },
            });
            zr.add(targetRing as never);
          }
        }
      }
      if (rightDragStart && Math.hypot(event.offsetX - rightDragStart.x, event.offsetY - rightDragStart.y) > 5) {
        rightDragMoved = true;
        pendingContextMenu = undefined;
      }
    });
    zr.on("mouseup", (event) => {
      panPosition = undefined;
      if (linkSourceId) {
        const target = findNodeAt(event.offsetX, event.offsetY);
        if (target && callbacksRef.current.canConnect(linkSourceId, target.id)) callbacksRef.current.onConnect(linkSourceId, target.id);
        clearLinkDrag();
        callbacksRef.current.onConnectionSourceChange(undefined);
      }
      const contextMenu = pendingContextMenu;
      if (rightDragMoved) {
        suppressContextMenuUntil = Date.now() + 250;
      } else if (rightDragStart && contextMenu) {
        contextMenu();
      }
      pendingContextMenu = undefined;
      rightDragStart = undefined;
      rightDragMoved = false;
    });
    zr.on("contextmenu", (event) => {
      event.event?.preventDefault();
      if (rightDragMoved || Date.now() < suppressContextMenuUntil) return;
      if (event.target) return;
      const bounds = elementRef.current!.getBoundingClientRect();
      const openContextMenu = () => callbacksRef.current.onBlankContext(bounds.left + event.offsetX, bounds.top + event.offsetY);
      if (rightDragStart) pendingContextMenu = openContextMenu;
      else openContextMenu();
    });
    zr.on("click", (event) => {
      if (event.target) return;
      callbacksRef.current.onBlankClick();
      if (callbacksRef.current.tool === "connect") callbacksRef.current.onConnectionSourceChange(undefined);
    });
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(elementRef.current);
    return () => {
      observer.disconnect();
      clearLinkDrag();
      chart.dispose();
      if (elementRef.current) delete elementRef.current.__networkChart;
      chartRef.current = undefined;
    };
  }, []);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || !chartReady) return;
    const structure = JSON.stringify({
      nodes: nodes.map((node) => node.id),
      edges: edges.map((edge) => [edge.id, edge.source, edge.target]),
    });
    const visual = JSON.stringify({
      nodes: nodes.map(({ id, title, subtitle, shortLabel, state, itemStyle }) => ({ id, title, subtitle, shortLabel, state, itemStyle })),
      edges: edges.map(({ id, name, lineStyle }) => ({ id, name, lineStyle })),
      tool,
    });
    const resetLayout = structure !== structureRef.current || layoutVersion !== layoutVersionRef.current;
    if (!resetLayout && visual === visualRef.current) return;
    structureRef.current = structure;
    visualRef.current = visual;
    layoutVersionRef.current = layoutVersion;
    chart.setOption({
      animation: true,
      animationDurationUpdate: 280,
      tooltip: {
        trigger: "item",
        confine: true,
        formatter: (params: { dataType: string; data: GraphNodeData | GraphEdgeData }) => {
          if (params.dataType === "edge") return escapeHtml((params.data as GraphEdgeData).name);
          const node = params.data as GraphNodeData;
          return [node.title, node.subtitle, node.meta, node.state].filter(Boolean).map((line) => escapeHtml(String(line))).join("<br>");
        },
      },
      series: [{
        id: "network",
        type: "graph",
        layout: "force",
        roam: "scale",
        ...(resetLayout ? { zoom: 0.82 } : {}),
        scaleLimit: { min: 0.45, max: 2.5 },
        draggable: tool === "select",
        data: nodes.map((node) => ({
          ...node,
          cursor: tool === "connect" ? "crosshair" : "grab",
          itemStyle: node.itemStyle,
          label: node.kind === "server"
            ? {
              show: true,
              formatter: `{state|${nodeStatusLabel(node.state)}}\n{name|${node.title}}`,
              position: "inside",
              rich: {
                state: { color: nodeStatusColor(node.state), fontSize: 8, fontWeight: 700, lineHeight: 14 },
                name: { color: "#0f172a", fontSize: 10, fontWeight: 700, lineHeight: 13 },
              },
            }
            : node.kind === "ingress"
              ? {
                show: true,
                formatter: `{code|${node.shortLabel}}\n{port|${node.title.split(":").pop()}}`,
                position: "inside",
                rich: {
                  code: { color: "#ffffff", fontSize: node.shortLabel.length > 7 ? 5.5 : node.shortLabel.length > 5 ? 6.5 : 8, fontWeight: 700, lineHeight: 11 },
                  port: { color: "rgba(255,255,255,0.82)", fontSize: 7, lineHeight: 9 },
                },
              }
              : { show: true, formatter: node.shortLabel, position: "inside", color: "#ffffff", fontSize: 7, fontWeight: 700 },
        })),
        links: edges,
        force: {
          initLayout: "circular",
          repulsion: [160, 700],
          gravity: 0.055,
          edgeLength: [115, 390],
          friction: 0.48,
          layoutAnimation: !window.matchMedia("(prefers-reduced-motion: reduce)").matches,
        },
        lineStyle: { opacity: 0.82 },
        edgeLabel: { show: false },
        emphasis: {
          focus: "adjacency",
          scale: 1.12,
          edgeLabel: { show: true, formatter: "{b}", color: "#334155", fontSize: 11, backgroundColor: "rgba(255,255,255,0.92)", padding: [3, 5], borderRadius: 3 },
        },
      }],
    }, { notMerge: resetLayout, lazyUpdate: false });
    if (elementRef.current) elementRef.current.dataset.nodeCount = String(nodes.length);
    if (resetLayout) {
      window.setTimeout(() => {
        if (chart.isDisposed()) return;
        const series = (chart as unknown as { getModel: () => { getSeriesByIndex: (index: number) => any } }).getModel().getSeriesByIndex(0);
        const data = series.getData();
        const coordinateSystem = series.coordinateSystem as { dataToPoint: (point: number[]) => number[] };
        const bounds = { left: Infinity, top: Infinity, right: -Infinity, bottom: -Infinity };
        for (let index = 0; index < data.count(); index += 1) {
          const [x, y] = coordinateSystem.dataToPoint(data.getItemLayout(index) as number[]);
          const radius = ((data.getRawDataItem(index) as GraphNodeData).symbolSize || 40) / 2 + 10;
          bounds.left = Math.min(bounds.left, x - radius);
          bounds.top = Math.min(bounds.top, y - radius);
          bounds.right = Math.max(bounds.right, x + radius);
          bounds.bottom = Math.max(bounds.bottom, y + radius);
        }
        if (!Number.isFinite(bounds.left)) return;
        const padding = 54;
        const graphWidth = bounds.right - bounds.left;
        const graphHeight = bounds.bottom - bounds.top;
        const scale = Math.min(1, (chart.getWidth() - padding * 2) / graphWidth, (chart.getHeight() - padding * 2) / graphHeight);
        const graphCenterX = (bounds.left + bounds.right) / 2;
        const graphCenterY = (bounds.top + bounds.bottom) / 2;
        if (scale < 0.995) chart.dispatchAction({ type: "graphRoam", seriesIndex: 0, zoom: scale, originX: graphCenterX, originY: graphCenterY });
        chart.dispatchAction({ type: "graphRoam", seriesIndex: 0, dx: chart.getWidth() / 2 - graphCenterX, dy: chart.getHeight() / 2 - graphCenterY });
      }, 900);
    }
  }, [chartReady, edges, layoutVersion, nodes, tool]);

  return <Box ref={elementRef} data-testid="network-canvas" data-canvas-tool={tool} cursor={tool === "connect" ? "crosshair" : "default"} w="100%" h={{ base: "600px", xl: "720px" }} />;
};

export const Network = () => {
  const { t } = useTranslation();
  const toast = useToast();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const reviewModal = useDisclosure();
  const [draft, setDraft] = useState<NetworkDraft>();
  const [selection, setSelection] = useState<Selection>(null);
  const [validation, setValidation] = useState<NetworkValidation>();
  const [layoutVersion, setLayoutVersion] = useState(0);
  const [canvasTool, setCanvasTool] = useState<CanvasTool>("select");
  const [connectionSourceId, setConnectionSourceId] = useState<string>();
  const [canvasMenu, setCanvasMenu] = useState<CanvasMenu>(null);
  const [validatedDraft, setValidatedDraft] = useState<NetworkDraft>();
  const [networkView, setNetworkView] = useState<"topology" | "resources">("topology");
  const workspace = useQuery(["singbox", "network"], () => fetch<NetworkWorkspace>("/singbox/network"), {
    refetchInterval: 10000,
  });
  const baselineDraft = useMemo(
    () => workspace.data ? toDraft(workspace.data) : undefined,
    [workspace.data],
  );
  const dirty = semanticDraftHash(draft) !== semanticDraftHash(baselineDraft);
  const draftForSave = draft && workspace.data
    ? { ...draft, base_topology_revision: workspace.data.topology_revision }
    : undefined;

  useEffect(() => {
    if (!workspace.data || !baselineDraft) return;
    if (!draft || !dirty) setDraft(baselineDraft);
  }, [baselineDraft, dirty, draft, workspace.data]);

  const validate = useMutation(
    () => fetch<NetworkValidation>("/singbox/network/drafts/validate", { method: "POST", body: draftForSave }),
    {
      onSuccess: (result) => {
        setValidation(result);
        if (result.valid && draftForSave) {
          setValidatedDraft(draftForSave);
          reviewModal.onOpen();
        }
      },
      onError: (error) => { generateErrorMessage(error, toast); },
    },
  );
  const apply = useMutation(
    () => fetch<{ topology_revision: number; route_revision: number }>("/singbox/network/drafts/apply", { method: "POST", body: validatedDraft }),
    {
      onSuccess: async (result) => {
        reviewModal.onClose();
        generateSuccessMessage(t("network.message.staged", { topology: result.topology_revision, route: result.route_revision }), toast);
        setValidation(undefined);
        setValidatedDraft(undefined);
        setSelection(null);
        const data = await queryClient.fetchQuery(["singbox", "network"], () => fetch<NetworkWorkspace>("/singbox/network"));
        setDraft(toDraft(data));
      },
      onError: (error) => { generateErrorMessage(error, toast); },
    },
  );

  const graphNodes = useMemo<GraphNodeData[]>(() => {
    if (!workspace.data || !draft) return [];
    const ingressGroups = new Map<number, IngressService[]>();
    const egressGroups = new Map<number, EgressService[]>();
    draft.ingresses.forEach((item) => ingressGroups.set(item.node_id, [...(ingressGroups.get(item.node_id) || []), item]));
    draft.egresses.forEach((item) => egressGroups.set(item.node_id, [...(egressGroups.get(item.node_id) || []), item]));
    const servers = workspace.data.nodes.map((node) => ({
      id: `server-${node.id}`,
      name: node.name,
      kind: "server" as const,
      title: node.name,
      subtitle: node.public_host,
      shortLabel: "S",
      meta: t("network.message.serviceCount", { ingresses: ingressGroups.get(node.id)?.length || 0, egresses: egressGroups.get(node.id)?.length || 0 }),
      state: node.status,
      nodeId: node.id,
      value: 3,
      symbolSize: 60,
      itemStyle: {
        color: "#f8fafc",
        borderColor: nodeStatusColor(node.status),
        borderWidth: 3,
        shadowBlur: 6,
        shadowColor: node.status === "connected" ? "rgba(22,163,74,0.2)" : node.status === "error" ? "rgba(220,38,38,0.2)" : "rgba(15,23,42,0.16)",
      },
    }));
    const ingresses = draft.ingresses.map((item, index): GraphNodeData => {
      const observed = workspace.data?.ingresses.find((value) => value.id === item.id);
      return {
        id: ingressNodeId(item, index),
        name: item.name,
        kind: "ingress",
        title: `${item.protocol}:${item.listen_port}`,
        subtitle: item.name,
        shortLabel: item.protocol.toUpperCase(),
        state: ingressOperState(item, observed),
        objectIndex: index,
        value: 1,
        symbolSize: 40,
        itemStyle: { color: item.enabled ? "#1d4ed8" : "#94a3b8", borderColor: item.enabled ? "#bfdbfe" : "#cbd5e1", borderWidth: 2, shadowBlur: 4, shadowColor: item.enabled ? "rgba(29,78,216,0.2)" : "rgba(15,23,42,0.14)" },
      };
    });
    const egresses = draft.egresses.map((item, index): GraphNodeData => ({
      id: egressNodeId(item, index),
      name: item.name,
      kind: "egress",
      title: t("network.option.direct").toUpperCase(),
      subtitle: item.name,
      shortLabel: t("network.option.direct").toUpperCase(),
      state: item.enabled ? "enabled" : "disabled",
      objectIndex: index,
      value: 1,
      symbolSize: 40,
      itemStyle: { color: item.enabled ? "#b45309" : "#94a3b8", borderColor: item.enabled ? "#fde68a" : "#cbd5e1", borderWidth: 2, shadowBlur: 4, shadowColor: item.enabled ? "rgba(180,83,9,0.2)" : "rgba(15,23,42,0.14)" },
    }));
    return [...servers, ...ingresses, ...egresses];
  }, [draft, t, workspace.data]);
  const graphEdges = useMemo<GraphEdgeData[]>(() => {
    if (!draft) return [];
    const attachments: GraphEdgeData[] = [
      ...draft.ingresses.filter((item) => item.node_id > 0).map((item) => {
        const index = draft.ingresses.indexOf(item);
        const observed = workspace.data?.ingresses.find((value) => value.id === item.id);
        const state = ingressOperState(item, observed);
        const color = operStateColor(state);
        return {
          id: `attach-${ingressNodeId(item, index)}`,
          source: ingressNodeId(item, index),
          target: `server-${item.node_id}`,
          name: item.name,
          kind: "ingress" as const,
          objectIndex: index,
          value: 3,
          symbol: ["none", "arrow"] as ["none", "arrow"],
          symbolSize: [0, 8] as [number, number],
          lineStyle: { color, width: 1.5, curveness: 0.08, type: state === "up" || state === "down" ? "solid" as const : "dashed" as const, opacity: item.enabled ? 0.9 : 0.65 },
        };
      }),
      ...draft.egresses.filter((item) => item.node_id > 0).map((item) => {
        const index = draft.egresses.indexOf(item);
        const nodeStatus = workspace.data?.nodes.find((node) => node.id === item.node_id)?.status;
        const color = item.enabled ? nodeStatusColor(nodeStatus) : "#94a3b8";
        return {
          id: `attach-${egressNodeId(item, index)}`,
          source: `server-${item.node_id}`,
          target: egressNodeId(item, index),
          name: item.name,
          kind: "egress" as const,
          objectIndex: index,
          value: 3,
          symbol: ["none", "arrow"] as ["none", "arrow"],
          symbolSize: [0, 8] as [number, number],
          lineStyle: { color, width: 1.5, curveness: 0.08, type: item.enabled ? "solid" as const : "dashed" as const, opacity: item.enabled ? 0.9 : 0.65 },
        };
      }),
    ];
    const links = draft.adjacencies.map((item, index): GraphEdgeData => {
      const state = directionState(workspace.data?.adjacencies.find((value) => value.id === item.id) || item);
      const id = `adjacency-${item.id ?? `new-${index}`}`;
      return {
        id,
        source: `server-${item.node_a_id}`,
        target: `server-${item.node_b_id}`,
        name: item.name,
        kind: "adjacency",
        objectIndex: index,
        value: 1,
        symbol: ["arrow", "arrow"],
        symbolSize: [10, 10],
        lineStyle: { color: state === "down" ? "#dc2626" : state === "up" ? "#16a34a" : "#64748b", width: 2.5, curveness: 0.04, type: state === "unknown" ? "dashed" : "solid", opacity: 0.9 },
      };
    });
    return [...attachments, ...links];
  }, [draft, workspace.data]);

  useEffect(() => {
    const warnBeforeUnload = (event: BeforeUnloadEvent) => {
      if (!dirty) return;
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warnBeforeUnload);
    return () => window.removeEventListener("beforeunload", warnBeforeUnload);
  }, [dirty]);
  const invalidateReview = () => {
    setValidation(undefined);
    setValidatedDraft(undefined);
  };
  const updateIngress = (index: number, patch: Partial<IngressService>) => {
    invalidateReview();
    setDraft((current) => current && ({ ...current, ingresses: current.ingresses.map((item, itemIndex) => itemIndex === index ? { ...item, ...patch } : item) }));
  };
  const updateEgress = (index: number, patch: Partial<EgressService>) => {
    invalidateReview();
    setDraft((current) => current && ({ ...current, egresses: current.egresses.map((item, itemIndex) => itemIndex === index ? { ...item, ...patch } : item) }));
  };
  const updateAdjacency = (index: number, item: Adjacency) => {
    invalidateReview();
    setDraft((current) => current && ({ ...current, adjacencies: current.adjacencies.map((value, itemIndex) => itemIndex === index ? item : value) }));
  };
  const updatePolicy = (index: number, patch: Partial<RoutingPolicy>) => {
    invalidateReview();
    setDraft((current) => current && ({ ...current, routing_policies: current.routing_policies.map((item, itemIndex) => itemIndex === index ? { ...item, ...patch } : item) }));
  };
  const resetLayout = () => setLayoutVersion((value) => value + 1);
  const nextPort = (current: NetworkDraft, reserved: number[] = []) => {
    const used = new Set([
      ...current.adjacencies.flatMap((item) => item.directions.map((direction) => direction.listen_port)),
      ...reserved,
    ]);
    let port = 20000;
    while (used.has(port)) port += 1;
    return port;
  };
  const addIngress = () => {
    if (!draft) return;
    const index = draft.ingresses.length;
    const listenPort = 12000 + index;
    const item: IngressService = {
      node_id: 0,
      name: t("network.default.ingress", { number: index + 1 }),
      protocol: "anytls",
      listen_port: listenPort,
      enabled: true,
      tls_mode: "system-ca",
      tls_profile: {},
      protocol_profile: defaultProfile("anytls"),
    };
    invalidateReview();
    setDraft({ ...draft, ingresses: [...draft.ingresses, item] });
    setSelection({ kind: "ingress", index });
    setCanvasMenu(null);
  };
  const addEgress = () => {
    if (!draft) return;
    const index = draft.egresses.length;
    const item: EgressService = { node_id: 0, name: t("network.default.egress", { number: index + 1 }), kind: "direct", enabled: true, settings: {} };
    invalidateReview();
    setDraft({ ...draft, egresses: [...draft.egresses, item] });
    setSelection({ kind: "egress", index });
    setCanvasMenu(null);
  };
  const addPolicy = () => {
    if (!draft) return;
    const index = draft.routing_policies.length;
    invalidateReview();
    setDraft({ ...draft, routing_policies: [...draft.routing_policies, {
      name: t("network.default.policy", { number: index + 1 }),
      metric_mode: "admin_only",
      max_hops: 8,
      allow_degraded: false,
      failover: true,
      required_node_ids: [],
      avoided_node_ids: [],
    }] });
    setSelection({ kind: "policy", index });
    setCanvasMenu(null);
  };
  const addAdjacency = () => {
    if (!draft || !workspace.data) return;
    const existing = new Set(draft.adjacencies.map((item) => `${item.node_a_id}:${item.node_b_id}`));
    let endpoints: [number, number] | undefined;
    for (let left = 0; left < workspace.data.nodes.length && !endpoints; left += 1) {
      for (let right = left + 1; right < workspace.data.nodes.length; right += 1) {
        const nodeA = workspace.data.nodes[left].id;
        const nodeB = workspace.data.nodes[right].id;
        if (!existing.has(`${Math.min(nodeA, nodeB)}:${Math.max(nodeA, nodeB)}`)) {
          endpoints = [Math.min(nodeA, nodeB), Math.max(nodeA, nodeB)];
          break;
        }
      }
    }
    if (!endpoints) {
      toast({ status: "warning", title: t("network.message.allPairsConnected") });
      return;
    }
    const [nodeA, nodeB] = endpoints;
    const port = nextPort(draft);
    const nameA = workspace.data.nodes.find((node) => node.id === nodeA)?.name || `${nodeA}`;
    const nameB = workspace.data.nodes.find((node) => node.id === nodeB)?.name || `${nodeB}`;
    const index = draft.adjacencies.length;
    invalidateReview();
    setDraft({ ...draft, adjacencies: [...draft.adjacencies, {
      node_a_id: nodeA,
      node_b_id: nodeB,
      name: `${nameA} <-> ${nameB}`,
      enabled: true,
      directions: [
        { from_node_id: nodeA, to_node_id: nodeB, enabled: true, transport: "anytls", listen_port: port, admin_cost: 100, settings: defaultProfile("anytls") },
        { from_node_id: nodeB, to_node_id: nodeA, enabled: true, transport: "anytls", listen_port: nextPort(draft, [port]), admin_cost: 100, settings: defaultProfile("anytls") },
      ],
    }] });
    setSelection({ kind: "adjacency", index });
    setCanvasMenu(null);
  };
  const updateNewAdjacencyEndpoint = (index: number, side: "a" | "b", nodeId: number) => {
    const adjacency = draft?.adjacencies[index];
    if (!draft || !adjacency || adjacency.id) return;
    const otherNodeId = side === "a" ? adjacency.node_b_id : adjacency.node_a_id;
    if (nodeId === otherNodeId) return;
    const nodeA = Math.min(nodeId, otherNodeId);
    const nodeB = Math.max(nodeId, otherNodeId);
    const nameA = workspace.data?.nodes.find((node) => node.id === nodeA)?.name || `${nodeA}`;
    const nameB = workspace.data?.nodes.find((node) => node.id === nodeB)?.name || `${nodeB}`;
    updateAdjacency(index, {
      ...adjacency,
      node_a_id: nodeA,
      node_b_id: nodeB,
      name: `${nameA} <-> ${nameB}`,
      directions: adjacency.directions.map((direction, directionIndex) => ({
        ...direction,
        from_node_id: directionIndex === 0 ? nodeA : nodeB,
        to_node_id: directionIndex === 0 ? nodeB : nodeA,
      })),
    });
  };
  const canConnectNodes = (sourceId: string, targetId: string) => {
    if (sourceId === targetId) return false;
    const source = graphNodes.find((node) => node.id === sourceId);
    const target = graphNodes.find((node) => node.id === targetId);
    if (!source || !target) return false;
    if (source.kind === "server" && target.kind === "server") {
      const nodeA = Math.min(source.nodeId || 0, target.nodeId || 0);
      const nodeB = Math.max(source.nodeId || 0, target.nodeId || 0);
      return !draft?.adjacencies.some((item) => item.node_a_id === nodeA && item.node_b_id === nodeB);
    }
    if ((source.kind === "server") === (target.kind === "server")) return false;
    const server = source.kind === "server" ? source : target;
    const service = source.kind === "server" ? target : source;
    if (!server.nodeId || service.objectIndex == null) return false;
    if (service.kind === "egress") return draft?.egresses[service.objectIndex]?.node_id !== server.nodeId;
    if (service.kind !== "ingress" || !draft) return false;
    const ingress = draft.ingresses[service.objectIndex];
    if (!ingress || ingress.node_id === server.nodeId) return false;
    if (!ingress.enabled) return true;
    const ingressConflict = draft.ingresses.some((item, index) => (
      index !== service.objectIndex
      && item.enabled
      && item.node_id === server.nodeId
      && item.listen_port === ingress.listen_port
    ));
    const directionConflict = draft.adjacencies.some((adjacency) => adjacency.enabled && adjacency.directions.some((direction) => (
      direction.enabled
      && direction.to_node_id === server.nodeId
      && direction.listen_port === ingress.listen_port
    )));
    return !ingressConflict && !directionConflict;
  };
  const handleConnect = (sourceId: string, targetId: string) => {
    if (sourceId === targetId || !draft || !workspace.data) return;
    const source = graphNodes.find((node) => node.id === sourceId);
    const target = graphNodes.find((node) => node.id === targetId);
    if (!source || !target) return;
    const server = source.kind === "server" ? source : target.kind === "server" ? target : undefined;
    const service = source.kind !== "server" ? source : target.kind !== "server" ? target : undefined;
    if (server && service && server.nodeId) {
      if (service.kind === "ingress" && service.objectIndex != null) updateIngress(service.objectIndex, { node_id: server.nodeId });
      if (service.kind === "egress" && service.objectIndex != null) updateEgress(service.objectIndex, { node_id: server.nodeId });
      return;
    }
    if (source.kind === "server" && target.kind === "server" && source.nodeId && target.nodeId) {
      const nodeA = Math.min(source.nodeId, target.nodeId);
      const nodeB = Math.max(source.nodeId, target.nodeId);
      if (draft.adjacencies.some((item) => item.node_a_id === nodeA && item.node_b_id === nodeB)) {
        toast({ status: "info", title: t("network.message.alreadyConnected") });
        return;
      }
      const port = nextPort(draft);
      const nameA = workspace.data.nodes.find((node) => node.id === nodeA)?.name || `${nodeA}`;
      const nameB = workspace.data.nodes.find((node) => node.id === nodeB)?.name || `${nodeB}`;
      invalidateReview();
      setDraft({ ...draft, adjacencies: [...draft.adjacencies, {
        node_a_id: nodeA,
        node_b_id: nodeB,
        name: `${nameA} <-> ${nameB}`,
        enabled: true,
        directions: [
          { from_node_id: nodeA, to_node_id: nodeB, enabled: true, transport: "anytls", listen_port: port, admin_cost: 100, settings: defaultProfile("anytls") },
          { from_node_id: nodeB, to_node_id: nodeA, enabled: true, transport: "anytls", listen_port: nextPort(draft, [port]), admin_cost: 100, settings: defaultProfile("anytls") },
        ],
      }] });
      return;
    }
    toast({ status: "warning", title: t("network.message.connectInvalid") });
  };

  if (workspace.isLoading || !workspace.data || !draft) return <VStack align="stretch"><PageHeader title={t("network.title")} /><Skeleton h="650px" /></VStack>;
  const selectedAdjacency = selection?.kind === "adjacency" ? draft.adjacencies[selection.index] : undefined;
  const selectedIngress = selection?.kind === "ingress" ? draft.ingresses[selection.index] : undefined;
  const selectedIngressObservation = selectedIngress?.id
    ? workspace.data?.ingresses.find((item) => item.id === selectedIngress.id)
    : undefined;
  const selectedIngressState = selectedIngress
    ? ingressOperState(selectedIngress, selectedIngressObservation)
    : undefined;
  const selectedIngressAddresses = selectedIngress
    ? workspace.data.addresses.filter((address) => address.node_id === selectedIngress.node_id && address.enabled)
    : [];
  const selectedEgress = selection?.kind === "egress" ? draft.egresses[selection.index] : undefined;
  const selectedPolicy = selection?.kind === "policy" ? draft.routing_policies[selection.index] : undefined;
  const selectedAdjacencyObservation = selectedAdjacency?.id
    ? workspace.data.adjacencies.find((item) => item.id === selectedAdjacency.id)
    : undefined;
  const selectedAdjacencyState = selectedAdjacency
    ? adjacencyOperState(selectedAdjacency, selectedAdjacencyObservation)
    : undefined;
  const selectedServer = selection?.kind === "server" ? workspace.data.nodes.find((node) => node.id === selection.nodeId) : undefined;
  const selectedIndex = selection && "index" in selection ? selection.index : -1;
  const stateLabel = (state?: string) => t(`network.state.${state || "unknown"}`, { defaultValue: state || t("network.state.unknown") });

  return (
    <VStack align="stretch" spacing={4}>
      <PageHeader title={t("network.title")} actions={<HStack>
        <Button size="sm" variant="outline" isDisabled={!dirty} onClick={() => { setDraft(baselineDraft); setValidation(undefined); setValidatedDraft(undefined); setSelection(null); }}>{t("network.action.discard")}</Button>
        <Button size="sm" colorScheme="primary" leftIcon={<CloudArrowUpIcon width="16px" />} isDisabled={!dirty} isLoading={validate.isLoading} onClick={() => validate.mutate()}>{t("network.action.save")}</Button>
      </HStack>} />
      <HStack justify="space-between" flexWrap="wrap">
        <HStack align="end" flexWrap="wrap">
          <Tabs
            size="sm"
            variant="line"
            colorScheme="primary"
            index={networkView === "topology" ? 0 : 1}
            onChange={(index) => { setNetworkView(index === 0 ? "topology" : "resources"); setCanvasMenu(null); }}
          >
            <TabList><Tab>{t("network.tab.topology")}</Tab><Tab>{t("network.tab.resources")}</Tab></TabList>
          </Tabs>
          <Badge>{t("network.badge.topologyRevision", { revision: workspace.data.topology_revision })}</Badge>
          {dirty && <Badge colorScheme="orange">{t("network.badge.draft")}</Badge>}
          {connectionSourceId && <Badge colorScheme="yellow">{t("network.badge.linkFrom", { name: graphNodes.find((node) => node.id === connectionSourceId)?.title })}</Badge>}
        </HStack>
        {networkView === "topology" && <HStack>
          <ButtonGroup size="xs" isAttached variant="outline">
            <Tooltip label={t("network.action.selectMove")}>
              <IconButton
                aria-label={t("network.action.selectMove")}
                aria-pressed={canvasTool === "select"}
                colorScheme={canvasTool === "select" ? "primary" : "gray"}
                variant={canvasTool === "select" ? "solid" : "outline"}
                icon={<CursorArrowRaysIcon width="14px" />}
                onClick={() => { setCanvasTool("select"); setConnectionSourceId(undefined); setCanvasMenu(null); }}
              />
            </Tooltip>
            <Tooltip label={t("network.action.connectNodes")}>
              <IconButton
                aria-label={t("network.action.connectNodes")}
                aria-pressed={canvasTool === "connect"}
                colorScheme={canvasTool === "connect" ? "primary" : "gray"}
                variant={canvasTool === "connect" ? "solid" : "outline"}
                icon={<LinkIcon width="14px" />}
                onClick={() => { setCanvasTool("connect"); setConnectionSourceId(undefined); setCanvasMenu(null); }}
              />
            </Tooltip>
          </ButtonGroup>
          <Tooltip label={t("network.action.relayout")}>
            <IconButton aria-label={t("network.action.relayout")} size="xs" variant="ghost" icon={<ArrowPathIcon width="14px" />} onClick={resetLayout} />
          </Tooltip>
        </HStack>}
      </HStack>
      {networkView === "resources" && <Text fontSize="xs" color="gray.500">{t("network.help.resources")}</Text>}
      {validation && !validation.valid && <Alert status="error"><AlertIcon /><AlertDescription>{validation.issues.map((issue) => issue.message).join("; ")}</AlertDescription></Alert>}
      {validation?.valid && <Alert status="success"><AlertIcon /><AlertDescription>{t("network.message.reachable", { reachable: validation.reachable_connections, affected: validation.affected_connections })}</AlertDescription></Alert>}
      <Grid templateColumns={{ base: "1fr", xl: networkView === "resources" ? "minmax(0, 1fr) 460px" : "minmax(0, 1fr) 380px" }} gap={4} minH="650px">
        {networkView === "topology" ? <Box border="1px solid" borderColor="gray.200" _dark={{ borderColor: "gray.700" }} minH="650px">
          <NetworkCanvas
            nodes={graphNodes}
            edges={graphEdges}
            layoutVersion={layoutVersion}
            tool={canvasTool}
            connectionSourceId={connectionSourceId}
            onConnect={handleConnect}
            canConnect={canConnectNodes}
            onConnectionSourceChange={setConnectionSourceId}
            onNodeContext={(node) => {
              if (node.kind === "server" && node.nodeId) setSelection({ kind: "server", nodeId: node.nodeId });
              if (node.kind === "ingress" && node.objectIndex != null) setSelection({ kind: "ingress", index: node.objectIndex });
              if (node.kind === "egress" && node.objectIndex != null) setSelection({ kind: "egress", index: node.objectIndex });
              setCanvasMenu(null);
            }}
            onEdgeContext={(edge) => {
              setSelection({ kind: edge.kind, index: edge.objectIndex });
              setCanvasMenu(null);
            }}
            onBlankContext={(x, y) => setCanvasMenu({ x, y })}
            onBlankClick={() => setCanvasMenu(null)}
          />
          {canvasMenu && <VStack
            position="fixed"
            left={`${canvasMenu.x}px`}
            top={`${canvasMenu.y}px`}
            zIndex={30}
            align="stretch"
            spacing={0}
            bg="white"
            _dark={{ bg: "gray.800" }}
            border="1px solid"
            borderColor="gray.200"
            boxShadow="lg"
            borderRadius="4px"
            py={1}
            minW="190px"
          >
            <Button size="sm" justifyContent="flex-start" variant="ghost" onClick={addIngress}>{t("network.action.addIngress")}</Button>
            <Button size="sm" justifyContent="flex-start" variant="ghost" onClick={addEgress}>{t("network.action.addEgress")}</Button>
            <Button size="sm" justifyContent="flex-start" variant="ghost" onClick={addPolicy}>{t("network.action.addPolicy")}</Button>
            {draft.routing_policies.map((policy, index) => <Button key={policy.id || `policy-${index}`} size="sm" justifyContent="flex-start" variant="ghost" onClick={() => { setSelection({ kind: "policy", index }); setCanvasMenu(null); }}>{t("network.menu.editPolicy", { name: policy.name })}</Button>)}
            <Button size="sm" justifyContent="flex-start" variant="ghost" onClick={() => navigate("/nodes")}>{t("network.menu.addServer")}</Button>
          </VStack>}
        </Box> : <NetworkResourceTables
          draft={draft}
          workspace={workspace.data}
          selected={selection}
          onSelect={(kind, index) => setSelection({ kind, index })}
          onManageServer={(nodeId) => navigate(`/nodes/${nodeId}`)}
          onAddServer={() => navigate("/nodes")}
          onAddIngress={addIngress}
          onAddEgress={addEgress}
          onAddAdjacency={addAdjacency}
          onAddPolicy={addPolicy}
        />}
        <Box
          borderLeft={{ base: "none", xl: "1px solid" }}
          borderTop={{ base: "1px solid", xl: "none" }}
          borderColor="gray.200"
          pl={{ base: 0, xl: 4 }}
          pt={{ base: 4, xl: 0 }}
          position={{ xl: "sticky" }}
          top={{ xl: "72px" }}
          alignSelf="start"
          maxH={{ xl: "calc(100vh - 88px)" }}
          overflowY={{ xl: "auto" }}
          pr={{ xl: 1 }}
        >
          {!selection && <Text fontSize="sm" color="gray.500">{t("network.message.noSelection")}</Text>}
          {selectedServer && <VStack align="stretch" spacing={3}>
            <Text fontWeight="semibold">{selectedServer.name}</Text>
            <FormControl><FormLabel fontSize="xs">{t("network.inspector.publicAddress")}</FormLabel><Input size="sm" value={selectedServer.public_host} isReadOnly /></FormControl>
            <HStack justify="space-between"><Text fontSize="sm">{t("network.inspector.serverStatus")}</Text><Badge colorScheme={selectedServer.status === "connected" ? "green" : "gray"}>{stateLabel(selectedServer.status)}</Badge></HStack>
            <Button size="sm" variant="outline" onClick={() => navigate(`/nodes/${selectedServer.id}`)}>{t("network.action.manageServer", { name: selectedServer.name })}</Button>
          </VStack>}
          {selectedIngress && <VStack align="stretch" spacing={3}>
            <HStack justify="space-between">
              <Box><Text fontWeight="semibold">{t("network.inspector.ingress")}</Text><Text fontSize="xs" color="gray.500">{selectedIngress.name}</Text></Box>
              <HStack><Badge colorScheme={selectedIngressState === "up" ? "green" : selectedIngressState === "down" ? "red" : selectedIngressState === "provisioning" ? "orange" : "gray"}>{stateLabel(selectedIngressState)}</Badge><IconButton aria-label={t("network.action.deleteIngress")} size="xs" variant="ghost" colorScheme="red" icon={<TrashIcon width="15px" />} onClick={() => { setDraft((current) => current && ({ ...current, ingresses: current.ingresses.filter((_, index) => index !== selectedIndex) })); invalidateReview(); setSelection(null); }} /></HStack>
            </HStack>
            <Tabs key={`ingress-editor-${selectedIngress.id || selectedIndex}`} size="sm" variant="line" colorScheme="primary" isLazy>
              <TabList><Tab>{t("network.tab.general")}</Tab><Tab>{t("network.tab.tls")}</Tab><Tab>{t("network.tab.protocol")}</Tab></TabList>
              <TabPanels>
                <TabPanel px={0} pt={4}><VStack align="stretch" spacing={3}>
                  {selectedIngressState !== "provisioning" && selectedIngressObservation?.message && <Text fontSize="xs" color="gray.500">{selectedIngressObservation.message}</Text>}
                  <FormControl><FormLabel fontSize="xs">{t("network.field.name")}</FormLabel><Input size="sm" value={selectedIngress.name} onChange={(event) => updateIngress(selectedIndex, { name: event.target.value })} /></FormControl>
                  <FormControl><FormLabel fontSize="xs">{t("network.field.server")}</FormLabel><Select size="sm" value={selectedIngress.node_id || ""} onChange={(event) => updateIngress(selectedIndex, { node_id: Number(event.target.value), advertised_address_id: null })}><option value="" disabled>{t("network.option.selectServer")}</option>{workspace.data.nodes.map((node) => <option key={node.id} value={node.id}>{node.name} / {node.public_host}</option>)}</Select></FormControl>
                  <FormControl><FormLabel fontSize="xs">{t("network.field.advertisedAddress")}</FormLabel><Select size="sm" value={selectedIngress.advertised_address_id || ""} onChange={(event) => updateIngress(selectedIndex, { advertised_address_id: event.target.value ? Number(event.target.value) : null })}><option value="">{t("network.option.primaryAddress")}</option>{selectedIngressAddresses.map((address) => <option key={address.id} value={address.id}>{address.address} / {address.kind}</option>)}</Select><FormHelperText>{t("network.help.advertisedAddress")}</FormHelperText></FormControl>
                  <Grid templateColumns={{ base: "1fr", md: "1fr 1fr" }} gap={3}>
                    <FormControl><FormLabel fontSize="xs">{t("network.field.protocol")}</FormLabel><Select size="sm" value={selectedIngress.protocol} onChange={(event) => { const protocol = event.target.value as SingBoxProtocol; updateIngress(selectedIndex, { protocol, protocol_profile: defaultProfile(protocol) }); }}>{SINGBOX_PROTOCOLS.map((protocol) => <option key={protocol}>{protocol}</option>)}</Select></FormControl>
                    <FormControl><FormLabel fontSize="xs">{t("network.field.listenPort")}</FormLabel><NumberInput size="sm" min={1} max={65535} value={selectedIngress.listen_port} onChange={(_, value) => updateIngress(selectedIndex, { listen_port: value })}><NumberInputField /></NumberInput></FormControl>
                  </Grid>
                  <HStack justify="space-between"><Text fontSize="sm">{t("network.field.enabled")}</Text><Switch isChecked={selectedIngress.enabled} onChange={(event) => updateIngress(selectedIndex, { enabled: event.target.checked })} /></HStack>
                </VStack></TabPanel>
                <TabPanel px={0} pt={4}><VStack align="stretch" spacing={3}>
                  <FormControl><FormLabel fontSize="xs">{t("network.field.tlsMode")}</FormLabel><Select size="sm" value={selectedIngress.tls_mode} onChange={(event) => updateIngress(selectedIndex, { tls_mode: event.target.value as SingBoxTLSMode })}><option value="system-ca">{t("network.option.systemCa")}</option><option value="ip-ca">{t("network.option.privateIpCa")}</option><option value="ip-insecure">{t("network.option.selfSigned")}</option></Select><FormHelperText>{t("network.help.tlsMode")}</FormHelperText></FormControl>
                  <FormControl><FormLabel fontSize="xs">{t("network.field.certificatePath")}</FormLabel><Input size="sm" fontFamily="mono" value={String(selectedIngress.tls_profile.cert_path || "")} onChange={(event) => updateIngress(selectedIndex, { tls_profile: { ...selectedIngress.tls_profile, cert_path: event.target.value || null } })} /></FormControl>
                  <FormControl><FormLabel fontSize="xs">{t("network.field.privateKeyPath")}</FormLabel><Input size="sm" fontFamily="mono" value={String(selectedIngress.tls_profile.key_path || "")} onChange={(event) => updateIngress(selectedIndex, { tls_profile: { ...selectedIngress.tls_profile, key_path: event.target.value || null } })} /></FormControl>
                  <FormControl><FormLabel fontSize="xs">{t("network.field.caCertificatePath")}</FormLabel><Input size="sm" fontFamily="mono" value={String(selectedIngress.tls_profile.ca_cert_path || "")} onChange={(event) => updateIngress(selectedIndex, { tls_profile: { ...selectedIngress.tls_profile, ca_cert_path: event.target.value || null } })} /></FormControl>
                </VStack></TabPanel>
                <TabPanel px={0} pt={4}>
                  {selectedIngress.protocol === "hysteria2" && <Hysteria2Editor value={{ ...DEFAULT_PROTOCOL_SETTINGS.hysteria2, ...selectedIngress.protocol_profile } as Hysteria2Settings} onChange={(protocol_profile) => updateIngress(selectedIndex, { protocol_profile })} />}
                  {selectedIngress.protocol === "tuic" && <TUICEditor value={{ ...DEFAULT_PROTOCOL_SETTINGS.tuic, ...selectedIngress.protocol_profile } as TUICSettings} onChange={(protocol_profile) => updateIngress(selectedIndex, { protocol_profile })} />}
                  {selectedIngress.protocol === "anytls" && <AnyTLSEditor value={{ ...DEFAULT_PROTOCOL_SETTINGS.anytls, ...selectedIngress.protocol_profile } as AnyTLSSettings} onChange={(protocol_profile) => updateIngress(selectedIndex, { protocol_profile })} />}
                  {!(["hysteria2", "tuic", "anytls"] as string[]).includes(selectedIngress.protocol) && <Text fontSize="sm" color="gray.500">{t("network.message.defaultProfile")}</Text>}
                </TabPanel>
              </TabPanels>
            </Tabs>
          </VStack>}
          {selectedEgress && <VStack align="stretch" spacing={3}>
            <HStack justify="space-between"><Text fontWeight="semibold">{t("network.inspector.directEgress")}</Text><IconButton aria-label={t("network.action.deleteEgress")} size="xs" variant="ghost" colorScheme="red" icon={<TrashIcon width="15px" />} onClick={() => { setDraft((current) => current && ({ ...current, egresses: current.egresses.filter((_, index) => index !== selectedIndex) })); invalidateReview(); setSelection(null); }} /></HStack>
            <FormControl><FormLabel fontSize="xs">{t("network.field.name")}</FormLabel><Input size="sm" value={selectedEgress.name} onChange={(event) => updateEgress(selectedIndex, { name: event.target.value })} /></FormControl>
            <FormControl><FormLabel fontSize="xs">{t("network.field.server")}</FormLabel><Select size="sm" value={selectedEgress.node_id || ""} onChange={(event) => updateEgress(selectedIndex, { node_id: Number(event.target.value) })}><option value="" disabled>{t("network.option.selectServer")}</option>{workspace.data.nodes.map((node) => <option key={node.id} value={node.id}>{node.name} / {node.public_host}</option>)}</Select></FormControl>
            <FormControl><FormLabel fontSize="xs">{t("network.field.kind")}</FormLabel><Select size="sm" value={selectedEgress.kind} isDisabled><option value="direct">{t("network.option.direct")}</option></Select></FormControl>
            <HStack justify="space-between"><Text fontSize="sm">{t("network.field.enabled")}</Text><Switch isChecked={selectedEgress.enabled} onChange={(event) => updateEgress(selectedIndex, { enabled: event.target.checked })} /></HStack>
          </VStack>}
          {selectedPolicy && <VStack align="stretch" spacing={3}>
            <HStack justify="space-between"><Box><Text fontWeight="semibold">{t("network.inspector.policy")}</Text><Text fontSize="xs" color="gray.500">{selectedPolicy.name}</Text></Box><IconButton aria-label={t("network.action.deletePolicy")} size="xs" variant="ghost" colorScheme="red" icon={<TrashIcon width="15px" />} onClick={() => { setDraft((current) => current && ({ ...current, routing_policies: current.routing_policies.filter((_, index) => index !== selectedIndex) })); invalidateReview(); setSelection(null); }} /></HStack>
            <Tabs key={`policy-editor-${selectedPolicy.id || selectedIndex}`} size="sm" variant="line" colorScheme="primary" isLazy>
              <TabList><Tab>{t("network.tab.general")}</Tab><Tab>{t("network.tab.constraints")}</Tab></TabList>
              <TabPanels>
                <TabPanel px={0} pt={4}><VStack align="stretch" spacing={3}>
                  <FormControl><FormLabel fontSize="xs">{t("network.field.name")}</FormLabel><Input size="sm" value={selectedPolicy.name} onChange={(event) => updatePolicy(selectedIndex, { name: event.target.value })} /></FormControl>
                  <FormControl><FormLabel fontSize="xs">{t("network.field.metricMode")}</FormLabel><Select size="sm" value={selectedPolicy.metric_mode} isDisabled><option value="admin_only">{t("network.option.adminCost")}</option></Select></FormControl>
                  <FormControl><FormLabel fontSize="xs">{t("network.field.maximumHops")}</FormLabel><NumberInput size="sm" min={1} max={8} value={selectedPolicy.max_hops} onChange={(_, value) => updatePolicy(selectedIndex, { max_hops: value })}><NumberInputField /></NumberInput><FormHelperText>{t("network.help.maxHops")}</FormHelperText></FormControl>
                  <HStack justify="space-between"><Text fontSize="sm">{t("network.field.automaticFailover")}</Text><Switch isChecked={selectedPolicy.failover} onChange={(event) => updatePolicy(selectedIndex, { failover: event.target.checked })} /></HStack>
                  <HStack justify="space-between"><Text fontSize="sm">{t("network.field.allowDegraded")}</Text><Switch isChecked={selectedPolicy.allow_degraded} onChange={(event) => updatePolicy(selectedIndex, { allow_degraded: event.target.checked })} /></HStack>
                </VStack></TabPanel>
                <TabPanel px={0} pt={4}><Grid templateColumns={{ base: "1fr", md: "1fr 1fr" }} gap={5}>
                  <VStack align="stretch" spacing={2}><Text fontSize="xs" fontWeight="semibold">{t("network.policy.requiredServers")}</Text>{workspace.data.nodes.map((node) => <Checkbox key={`required-${node.id}`} isChecked={selectedPolicy.required_node_ids.includes(node.id)} onChange={(event) => updatePolicy(selectedIndex, { required_node_ids: event.target.checked ? [...selectedPolicy.required_node_ids, node.id] : selectedPolicy.required_node_ids.filter((id) => id !== node.id) })}>{node.name}</Checkbox>)}</VStack>
                  <VStack align="stretch" spacing={2}><Text fontSize="xs" fontWeight="semibold">{t("network.policy.avoidedServers")}</Text>{workspace.data.nodes.map((node) => <Checkbox key={`avoided-${node.id}`} isChecked={selectedPolicy.avoided_node_ids.includes(node.id)} onChange={(event) => updatePolicy(selectedIndex, { avoided_node_ids: event.target.checked ? [...selectedPolicy.avoided_node_ids, node.id] : selectedPolicy.avoided_node_ids.filter((id) => id !== node.id) })}>{node.name}</Checkbox>)}</VStack>
                </Grid></TabPanel>
              </TabPanels>
            </Tabs>
          </VStack>}
          {selectedAdjacency && <VStack align="stretch" spacing={3}>
            <HStack justify="space-between">
              <Box><Text fontWeight="semibold">{t("network.inspector.adjacency")}</Text><Text fontSize="xs" color="gray.500">{selectedAdjacency.name}</Text></Box>
              <HStack>
                <Badge colorScheme={selectedAdjacencyState === "up" ? "green" : selectedAdjacencyState === "down" ? "red" : selectedAdjacencyState === "provisioning" ? "orange" : "gray"}>{stateLabel(selectedAdjacencyState)}</Badge>
                <IconButton aria-label={t("network.action.deleteAdjacency")} size="xs" variant="ghost" colorScheme="red" icon={<TrashIcon width="15px" />} onClick={() => { setDraft((current) => current && ({ ...current, adjacencies: current.adjacencies.filter((_, index) => index !== selectedIndex) })); invalidateReview(); setSelection(null); }} />
              </HStack>
            </HStack>
            <Tabs key={`adjacency-editor-${selectedAdjacency.id || selectedIndex}`} size="sm" variant="line" colorScheme="primary" isLazy>
              <TabList overflowX="auto" overflowY="hidden">
                <Tab>{t("network.tab.general")}</Tab>
                {selectedAdjacency.directions.map((direction) => {
                  const source = workspace.data.nodes.find((node) => node.id === direction.from_node_id)?.name || `Node ${direction.from_node_id}`;
                  const target = workspace.data.nodes.find((node) => node.id === direction.to_node_id)?.name || `Node ${direction.to_node_id}`;
                  return <Tab key={`tab-${direction.id || `${direction.from_node_id}-${direction.to_node_id}`}`} whiteSpace="nowrap">{source} → {target}</Tab>;
                })}
              </TabList>
              <TabPanels>
                <TabPanel px={0} pt={4}><VStack align="stretch" spacing={3}>
                  <FormControl><FormLabel fontSize="xs">{t("network.field.name")}</FormLabel><Input size="sm" value={selectedAdjacency.name} onChange={(event) => updateAdjacency(selectedIndex, { ...selectedAdjacency, name: event.target.value })} /></FormControl>
                  <Grid templateColumns={{ base: "1fr", md: "1fr 1fr" }} gap={3}>
                    <FormControl><FormLabel fontSize="xs">{t("network.field.serverA")}</FormLabel><Select size="sm" value={selectedAdjacency.node_a_id} isDisabled={Boolean(selectedAdjacency.id)} onChange={(event) => updateNewAdjacencyEndpoint(selectedIndex, "a", Number(event.target.value))}>{workspace.data.nodes.map((node) => <option key={node.id} value={node.id} disabled={node.id === selectedAdjacency.node_b_id}>{node.name}</option>)}</Select></FormControl>
                    <FormControl><FormLabel fontSize="xs">{t("network.field.serverB")}</FormLabel><Select size="sm" value={selectedAdjacency.node_b_id} isDisabled={Boolean(selectedAdjacency.id)} onChange={(event) => updateNewAdjacencyEndpoint(selectedIndex, "b", Number(event.target.value))}>{workspace.data.nodes.map((node) => <option key={node.id} value={node.id} disabled={node.id === selectedAdjacency.node_a_id}>{node.name}</option>)}</Select></FormControl>
                  </Grid>
                  {selectedAdjacency.id && <Text fontSize="xs" color="gray.500">{t("network.adjacency.endpointImmutable")}</Text>}
                  <HStack justify="space-between"><Text fontSize="sm">{t("network.field.enabled")}</Text><Switch isChecked={selectedAdjacency.enabled} onChange={(event) => updateAdjacency(selectedIndex, { ...selectedAdjacency, enabled: event.target.checked })} /></HStack>
                </VStack></TabPanel>
                {selectedAdjacency.directions.map((direction, directionIndex) => {
                  const source = workspace.data.nodes.find((node) => node.id === direction.from_node_id)?.name || `Node ${direction.from_node_id}`;
                  const target = workspace.data.nodes.find((node) => node.id === direction.to_node_id)?.name || `Node ${direction.to_node_id}`;
                  const observed = workspace.data.adjacencies.flatMap((item) => item.directions).find((item) => item.id === direction.id);
                  return <TabPanel key={`panel-${direction.id || `${direction.from_node_id}-${direction.to_node_id}`}`} px={0} pt={4}>
                    <VStack align="stretch" spacing={4}>
                      <HStack justify="space-between">
                        <Box><Text fontSize="sm" fontWeight="semibold">{source} → {target}</Text><Text fontSize="xs" color="gray.500">{observed?.rtt_ms != null ? t("network.adjacency.roundTrip", { value: observed.rtt_ms }) : t("network.adjacency.noProbe")}</Text></Box>
                        <Badge colorScheme={observed?.oper_state === "up" ? "green" : observed?.oper_state === "down" ? "red" : "gray"}>{stateLabel(observed?.oper_state || "new")}</Badge>
                      </HStack>
                      <FormControl><FormLabel fontSize="xs">{t("network.field.transport")}</FormLabel><Select size="sm" value={direction.transport} onChange={(event) => { const transport = event.target.value as "anytls" | "hysteria2"; const directions = selectedAdjacency.directions.map((item, index) => index === directionIndex ? { ...item, transport, settings: defaultProfile(transport) } : item); updateAdjacency(selectedIndex, { ...selectedAdjacency, directions }); }}><option value="anytls">AnyTLS</option><option value="hysteria2">Hysteria2</option></Select></FormControl>
                      <Grid templateColumns={{ base: "1fr", md: "1fr 1fr" }} gap={3}>
                        <FormControl><FormLabel fontSize="xs">{t("network.field.targetPort")}</FormLabel><NumberInput size="sm" value={direction.listen_port} min={1} max={65535} onChange={(_, value) => { const directions = selectedAdjacency.directions.map((item, index) => index === directionIndex ? { ...item, listen_port: value } : item); updateAdjacency(selectedIndex, { ...selectedAdjacency, directions }); }}><NumberInputField /></NumberInput></FormControl>
                        <FormControl><FormLabel fontSize="xs">{t("network.field.cost")}</FormLabel><NumberInput size="sm" value={direction.admin_cost} min={1} max={65535} onChange={(_, value) => { const directions = selectedAdjacency.directions.map((item, index) => index === directionIndex ? { ...item, admin_cost: value } : item); updateAdjacency(selectedIndex, { ...selectedAdjacency, directions }); }}><NumberInputField /></NumberInput><FormHelperText>{t("network.help.cost")}</FormHelperText></FormControl>
                      </Grid>
                      <HStack justify="space-between"><Text fontSize="sm">{t("network.field.directionEnabled")}</Text><Switch isChecked={direction.enabled} onChange={(event) => { const directions = selectedAdjacency.directions.map((item, index) => index === directionIndex ? { ...item, enabled: event.target.checked } : item); updateAdjacency(selectedIndex, { ...selectedAdjacency, directions }); }} /></HStack>
                      <Box borderTop="1px solid" borderColor="gray.200" pt={4}>
                        <Text fontSize="xs" fontWeight="semibold" mb={3}>{t("network.adjacency.transportProfile")}</Text>
                        {direction.transport === "hysteria2" && <Hysteria2Editor value={{ ...DEFAULT_PROTOCOL_SETTINGS.hysteria2, ...direction.settings } as Hysteria2Settings} onChange={(settings) => { const directions = selectedAdjacency.directions.map((item, index) => index === directionIndex ? { ...item, settings } : item); updateAdjacency(selectedIndex, { ...selectedAdjacency, directions }); }} />}
                        {direction.transport === "anytls" && <AnyTLSEditor value={{ ...DEFAULT_PROTOCOL_SETTINGS.anytls, ...direction.settings } as AnyTLSSettings} onChange={(settings) => { const directions = selectedAdjacency.directions.map((item, index) => index === directionIndex ? { ...item, settings } : item); updateAdjacency(selectedIndex, { ...selectedAdjacency, directions }); }} />}
                      </Box>
                    </VStack>
                  </TabPanel>;
                })}
              </TabPanels>
            </Tabs>
          </VStack>}
        </Box>
      </Grid>

      <Modal isOpen={reviewModal.isOpen} onClose={reviewModal.onClose} isCentered>
        <ModalOverlay /><ModalContent><ModalHeader>{t("network.modal.saveTopology")}</ModalHeader><ModalCloseButton /><ModalBody>
          <Grid templateColumns="1fr auto" gap={2} fontSize="sm">
            <Text color="gray.500">{t("network.field.baseRevision")}</Text><Text fontFamily="mono">r{draftForSave?.base_topology_revision}</Text>
            <Text color="gray.500">{t("network.resource.ingresses")}</Text><Text>{draft.ingresses.filter((item) => item.enabled).length}</Text>
            <Text color="gray.500">{t("network.resource.egresses")}</Text><Text>{draft.egresses.filter((item) => item.enabled).length}</Text>
            <Text color="gray.500">{t("network.field.activeDirections")}</Text><Text>{draft.adjacencies.flatMap((item) => item.directions).filter((item) => item.enabled).length}</Text>
            <Text color="gray.500">{t("network.resource.policies")}</Text><Text>{draft.routing_policies.length}</Text>
            <Text color="gray.500">{t("network.field.reachableConnections")}</Text><Text>{validation?.reachable_connections || 0} / {validation?.affected_connections || 0}</Text>
          </Grid>
        </ModalBody><ModalFooter><Button variant="ghost" mr={2} onClick={reviewModal.onClose}>{t("network.action.cancel")}</Button><Button colorScheme="primary" leftIcon={<CloudArrowUpIcon width="16px" />} isLoading={apply.isLoading} onClick={() => apply.mutate()}>{t("network.action.saveRevision")}</Button></ModalFooter></ModalContent>
      </Modal>
    </VStack>
  );
};
