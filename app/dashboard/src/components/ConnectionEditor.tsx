import {
  Badge,
  Box,
  Button,
  Checkbox,
  FormControl,
  FormLabel,
  HStack,
  Input,
  Select,
  Table,
  TableContainer,
  Tbody,
  Td,
  Text,
  Th,
  Thead,
  Tr,
  VStack,
  useColorModeValue,
} from "@chakra-ui/react";
import { PlusIcon, TrashIcon } from "@heroicons/react/24/outline";
import {
  Background,
  Controls,
  Edge,
  Handle,
  MarkerType,
  Node,
  NodeProps,
  Position,
  ReactFlow,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useMemo, useState } from "react";
import { useQuery } from "react-query";
import { useTranslation } from "react-i18next";
import { fetch } from "service/http";
import {
  ConnectionDraft,
  ConnectionRoute,
  EgressService,
  IngressService,
  NetworkWorkspace,
} from "types/SingBox";

type RouteNodeData = {
  kind: "endpoint" | "service" | "server";
  title: string;
  subtitle: string;
  tone?: "entry" | "exit";
};

const RouteNode = ({ data }: NodeProps) => {
  const node = data as RouteNodeData;
  const endpoint = node.kind === "endpoint";
  return (
    <Box
      minW={endpoint ? "110px" : "150px"}
      bg={endpoint ? (node.tone === "entry" ? "blue.600" : "teal.600") : "white"}
      _dark={{ bg: endpoint ? undefined : "gray.800" }}
      color={endpoint ? "white" : undefined}
      border="1px solid"
      borderColor="gray.300"
      borderRadius="6px"
      boxShadow="sm"
      px={3}
      py={2.5}
    >
      <Handle type="target" position={Position.Left} style={{ width: 10, height: 10 }} />
      <Text fontSize="sm" fontWeight="700">{node.title}</Text>
      <Text fontSize="xs" opacity={0.76} maxW="180px" isTruncated>{node.subtitle}</Text>
      <Handle type="source" position={Position.Right} style={{ width: 10, height: 10 }} />
    </Box>
  );
};

const nodeTypes = { route: RouteNode };
const tempId = () => `new-${Date.now()}-${Math.random().toString(16).slice(2)}`;

const ingressName = (service: IngressService | undefined, missing: string) =>
  service ? `${service.node_name || service.node_id} / ${service.protocol}:${service.listen_port}` : missing;

const egressName = (service: EgressService | undefined, missing: string) => service?.name || missing;

export const ConnectionEditor = ({
  connections,
  onChange,
  network,
  mode,
  selectedConnectionId,
  onSelectConnection,
}: {
  connections: ConnectionDraft[];
  onChange: (connections: ConnectionDraft[]) => void;
  network: NetworkWorkspace;
  mode: "graph" | "table";
  selectedConnectionId?: string;
  onSelectConnection: (clientId: string) => void;
}) => {
  const { t } = useTranslation();
  const selected = connections.find((connection) => connection.clientId === selectedConnectionId);
  const selectedIngress = network.ingresses.find((service) => service.id === selected?.ingress_service_id);
  const selectedEgress = network.egresses.find((service) => service.id === selected?.egress_service_id);
  const route = useQuery(
    ["singbox", "connection-route", selected?.id],
    () => fetch<ConnectionRoute>(`/singbox/connections/${selected!.id}/route`),
    { enabled: Boolean(selected?.id), refetchInterval: 5000 },
  );
  const canvasBg = useColorModeValue("#f8fafc", "#111827");

  const update = (clientId: string, patch: Partial<ConnectionDraft>) =>
    onChange(connections.map((connection) => connection.clientId === clientId ? { ...connection, ...patch } : connection));

  const selectIngress = (connection: ConnectionDraft, serviceId: number) => {
    const service = network.ingresses.find((item) => item.id === serviceId);
    if (!service) return;
    update(connection.clientId, {
      ingress_service_id: service.id,
      entry_node_id: service.node_id,
      protocol: service.protocol,
      label: `${service.name} -> ${egressName(network.egresses.find((item) => item.id === connection.egress_service_id), t("connections.missingEgress"))}`,
    });
  };

  const selectEgress = (connection: ConnectionDraft, serviceId: number) => {
    const service = network.egresses.find((item) => item.id === serviceId);
    if (!service) return;
    const ingress = network.ingresses.find((item) => item.id === connection.ingress_service_id);
    update(connection.clientId, {
      egress_service_id: service.id,
      exit_node_id: service.node_id === ingress?.node_id ? null : service.node_id,
      label: `${ingress?.name || t("connections.ingress")} -> ${service.name}`,
    });
  };

  const addConnection = () => {
    const ingress = network.ingresses.find((item) => item.enabled);
    const egress = network.egresses.find((item) => item.enabled && item.node_id === ingress?.node_id)
      || network.egresses.find((item) => item.enabled);
    const policy = network.routing_policies[0];
    if (!ingress || !egress || !policy) return;
    const clientId = tempId();
    onChange([...connections, {
      clientId,
      label: `${ingress.name} -> ${egress.name}`,
      protocol: ingress.protocol,
      entry_node_id: ingress.node_id,
      exit_node_id: egress.node_id === ingress.node_id ? null : egress.node_id,
      ingress_service_id: ingress.id,
      egress_service_id: egress.id,
      routing_policy_id: policy.id,
      enabled: true,
      sort_order: (connections.length + 1) * 100,
    }]);
    onSelectConnection(clientId);
  };

  const topologyNodes = useMemo<Node[]>(() => {
    if (!selected || !selectedIngress || !selectedEgress) return [];
    const serverIds = route.data?.status === "reachable"
      ? [selectedIngress.node_id, ...(route.data.hops || []).map((hop) => hop.to_node_id)]
      : [selectedIngress.node_id, ...(selectedEgress.node_id === selectedIngress.node_id ? [] : [selectedEgress.node_id])];
    const uniqueServers = serverIds.filter((id, index) => serverIds.indexOf(id) === index);
    const items: Node[] = [
      { id: "entry", type: "route", position: { x: 0, y: 190 }, data: { kind: "endpoint", tone: "entry", title: t("connections.entry").toUpperCase(), subtitle: t("connections.client") } },
      { id: "ingress", type: "route", position: { x: 160, y: 190 }, data: { kind: "service", title: `${selectedIngress.protocol}:${selectedIngress.listen_port}`, subtitle: selectedIngress.name } },
      ...uniqueServers.map((nodeId, index) => {
        const server = network.nodes.find((node) => node.id === nodeId);
        return { id: `server-${nodeId}`, type: "route", position: { x: 360 + index * 240, y: 190 }, data: { kind: "server", title: server?.name || `Node ${nodeId}`, subtitle: server?.public_host || "" } };
      }),
      { id: "egress", type: "route", position: { x: 360 + uniqueServers.length * 240, y: 190 }, data: { kind: "service", title: t("network.option.direct").toUpperCase(), subtitle: selectedEgress.name } },
      { id: "exit", type: "route", position: { x: 540 + uniqueServers.length * 240, y: 190 }, data: { kind: "endpoint", tone: "exit", title: t("connections.exit").toUpperCase(), subtitle: t("connections.internet") } },
    ];
    return items;
  }, [network.nodes, route.data, selected, selectedEgress, selectedIngress, t]);
  const topologyEdges = useMemo<Edge[]>(() => {
    if (!selectedIngress || !selectedEgress) return [];
    const path = route.data?.hops || [];
    const serverIds = route.data?.status === "reachable"
      ? [selectedIngress.node_id, ...path.map((hop) => hop.to_node_id)]
      : [selectedIngress.node_id, ...(selectedEgress.node_id === selectedIngress.node_id ? [] : [selectedEgress.node_id])];
    const uniqueServers = serverIds.filter((id, index) => serverIds.indexOf(id) === index);
    const edge = (id: string, source: string, target: string, label: string, color = "#2563eb"): Edge => ({
      id, source, target, label, markerEnd: { type: MarkerType.ArrowClosed, color },
      style: { stroke: color, strokeWidth: 2 }, labelStyle: { fill: color, fontSize: 11 },
    });
    return [
      edge("entry-ingress", "entry", "ingress", t("connections.subscription")),
      edge("ingress-server", "ingress", `server-${selectedIngress.node_id}`, `${selectedIngress.protocol}:${selectedIngress.listen_port}`),
      ...path.map((hop) => edge(`hop-${hop.position}`, `server-${hop.from_node_id}`, `server-${hop.to_node_id}`, t("connections.transportCost", { transport: hop.transport, cost: hop.admin_cost }), "#16a34a")),
      edge("server-egress", `server-${uniqueServers[uniqueServers.length - 1]}`, "egress", route.data?.status === "reachable" ? t("connections.cost", { cost: route.data.total_cost }) : t("connections.unresolved"), route.data?.status === "unreachable" ? "#dc2626" : "#0f766e"),
      edge("egress-exit", "egress", "exit", t("network.option.direct"), "#0f766e"),
    ];
  }, [route.data, selectedEgress, selectedIngress, t]);

  if (mode === "graph") {
    if (!selected) return <Box py={12} textAlign="center" color="gray.500">{t("connections.noSelection")}</Box>;
    return <VStack align="stretch" spacing={3}>
      <HStack align="end" flexWrap="wrap">
        <FormControl maxW="250px"><FormLabel fontSize="xs">{t("connections.connection")}</FormLabel><Select size="sm" value={selected.clientId} onChange={(event) => onSelectConnection(event.target.value)}>{connections.map((connection) => <option key={connection.clientId} value={connection.clientId}>{connection.label}</option>)}</Select></FormControl>
        <FormControl maxW="280px"><FormLabel fontSize="xs">{t("network.inspector.ingress")}</FormLabel><Select size="sm" value={selected.ingress_service_id || ""} onChange={(event) => selectIngress(selected, Number(event.target.value))}>{network.ingresses.filter((item) => item.enabled).map((item) => <option key={item.id} value={item.id}>{ingressName(item, t("connections.missingIngress"))}</option>)}</Select></FormControl>
        <FormControl maxW="260px"><FormLabel fontSize="xs">{t("connections.egressService")}</FormLabel><Select size="sm" value={selected.egress_service_id || ""} onChange={(event) => selectEgress(selected, Number(event.target.value))}>{network.egresses.filter((item) => item.enabled).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</Select></FormControl>
        <FormControl maxW="180px"><FormLabel fontSize="xs">{t("network.inspector.policy")}</FormLabel><Select size="sm" value={selected.routing_policy_id || ""} onChange={(event) => update(selected.clientId, { routing_policy_id: Number(event.target.value) })}>{network.routing_policies.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</Select></FormControl>
        <Badge colorScheme={route.data?.status === "reachable" ? "green" : route.data?.status === "unreachable" ? "red" : "gray"}>{t(`connections.state.${route.data?.status || (selected.id ? "loading" : "notApplied")}`)}</Badge>
      </HStack>
      <Box h="520px" border="1px solid" borderColor="gray.200" _dark={{ borderColor: "gray.700" }}>
        <ReactFlow key={`${selected.clientId}-${route.data?.route_revision || "pending"}-${topologyNodes.length}`} nodes={topologyNodes} edges={topologyEdges} nodeTypes={nodeTypes} nodesDraggable={false} fitView fitViewOptions={{ padding: 0.05 }} minZoom={0.25} maxZoom={1.5}>
          <Background color={useColorModeValue("#cbd5e1", "#334155")} bgColor={canvasBg} gap={20} size={1} />
          <Controls showInteractive={false} />
        </ReactFlow>
      </Box>
      {route.data && <HStack color="gray.500" fontSize="xs"><Text>{t("connections.topologyRevision", { revision: route.data.topology_revision || "-" })}</Text><Text>{t("connections.routeRevision", { revision: route.data.route_revision || "-" })}</Text><Text>{t("connections.hops", { count: route.data.hop_count || 0 })}</Text><Text>{route.data.reason}</Text></HStack>}
      {route.data?.candidates?.length ? <Box borderTop="1px solid" borderColor="gray.200" pt={2}>
        <Text fontSize="xs" fontWeight="semibold" mb={1}>{t("connections.whyPath")}</Text>
        <HStack flexWrap="wrap">{route.data.candidates.map((candidate) => <Badge key={candidate.adjacency_direction_ids.join("-") || "direct"} colorScheme={candidate.selected ? "green" : "gray"}>{candidate.node_names.join(" → ")} · {t("connections.cost", { cost: candidate.total_cost })}</Badge>)}</HStack>
      </Box> : null}
    </VStack>;
  }

  return <VStack align="stretch" spacing={3}>
    <HStack justify="space-between"><Text fontSize="sm" color="gray.500">{t("connections.intentHelp")}</Text><Button size="sm" leftIcon={<PlusIcon width="15px" />} onClick={addConnection}>{t("connections.addConnection")}</Button></HStack>
    <TableContainer border="1px solid" borderColor="gray.200" _dark={{ borderColor: "gray.700" }}>
      <Table size="sm"><Thead><Tr><Th>{t("connections.label")}</Th><Th>{t("connections.ingress")}</Th><Th>{t("connections.egress")}</Th><Th>{t("connections.policy")}</Th><Th>{t("network.field.enabled")}</Th><Th /></Tr></Thead><Tbody>
        {connections.map((connection) => {
          const ingress = network.ingresses.find((item) => item.id === connection.ingress_service_id);
          const egress = network.egresses.find((item) => item.id === connection.egress_service_id);
          return <Tr key={connection.clientId} bg={connection.clientId === selectedConnectionId ? "gray.50" : undefined} _dark={{ bg: connection.clientId === selectedConnectionId ? "gray.700" : undefined }}>
            <Td><Input size="sm" value={connection.label} onFocus={() => onSelectConnection(connection.clientId)} onChange={(event) => update(connection.clientId, { label: event.target.value })} /></Td>
            <Td><Select size="sm" value={connection.ingress_service_id || ""} onChange={(event) => selectIngress(connection, Number(event.target.value))}>{network.ingresses.filter((item) => item.enabled).map((item) => <option key={item.id} value={item.id}>{ingressName(item, t("connections.missingIngress"))}</option>)}</Select></Td>
            <Td><Select size="sm" value={connection.egress_service_id || ""} onChange={(event) => selectEgress(connection, Number(event.target.value))}>{network.egresses.filter((item) => item.enabled).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</Select></Td>
            <Td><Select size="sm" value={connection.routing_policy_id || ""} onChange={(event) => update(connection.clientId, { routing_policy_id: Number(event.target.value) })}>{network.routing_policies.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</Select></Td>
            <Td><Checkbox isChecked={connection.enabled} onChange={(event) => update(connection.clientId, { enabled: event.target.checked })} /></Td>
            <Td isNumeric><Button aria-label={t("connections.deleteNamed", { name: connection.label })} size="xs" variant="ghost" colorScheme="red" onClick={() => onChange(connections.filter((item) => item.clientId !== connection.clientId))}><TrashIcon width="15px" /></Button></Td>
          </Tr>;
        })}
      </Tbody></Table>
    </TableContainer>
  </VStack>;
};
