import {
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
  Tooltip,
  Tr,
  VStack,
  useColorModeValue,
} from "@chakra-ui/react";
import { Cog6ToothIcon, PlusIcon, TrashIcon } from "@heroicons/react/24/outline";
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
  useNodesState,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useEffect, useMemo, useState } from "react";
import { ConnectionDraft, DEFAULT_PUBLIC_PORTS, SINGBOX_PROTOCOLS, SingBoxNode, SingBoxNodeLink, SingBoxProtocol } from "types/SingBox";

type TopologyNodeData = {
  label: string;
  host?: string;
  kind: "endpoint" | "server";
  endpoint?: "entry" | "exit";
  acceptsInput: boolean;
  emitsOutput: boolean;
  status?: string;
};

const TopologyNode = ({ data }: NodeProps) => {
  const node = data as TopologyNodeData;
  return (
    <Box
      minW="150px"
      bg={node.kind === "endpoint" ? (node.endpoint === "entry" ? "blue.600" : "teal.600") : "white"}
      color={node.kind === "endpoint" ? "white" : "gray.800"}
      border="1px solid"
      borderColor={node.kind === "endpoint" || node.status === "connected" ? "gray.300" : "orange.300"}
      borderRadius="6px"
      boxShadow="sm"
      px={3}
      py={2.5}
    >
      {node.acceptsInput && <Handle type="target" id="in" position={Position.Left} style={{ width: 11, height: 11, background: "#0f766e" }} />}
      <HStack justify="space-between">
        <Text fontSize={node.kind === "endpoint" ? "md" : "sm"} fontWeight="bold">{node.label}</Text>
        {node.kind === "server" && <Box w="7px" h="7px" borderRadius="full" bg={node.status === "connected" ? "green.400" : "orange.400"} />}
      </HStack>
      <Text fontSize="10px" color={node.kind === "endpoint" ? "whiteAlpha.800" : "gray.500"} maxW="150px" isTruncated>{node.host}</Text>
      {node.emitsOutput && <Handle type="source" id="out" position={Position.Right} style={{ width: 11, height: 11, background: "#2563eb" }} />}
    </Box>
  );
};

const nodeTypes = { topology: TopologyNode };
const tempId = () => `new-${Date.now()}-${Math.random().toString(16).slice(2)}`;

const defaultLabel = (entry: SingBoxNode, exit: SingBoxNode | undefined, protocol: SingBoxProtocol) =>
  `${entry.name} -> ${exit?.name || "Direct"} / ${protocol}`;

const connectionPort = (connection: ConnectionDraft, nodes: SingBoxNode[]) => {
  const entry = nodes.find((node) => node.id === connection.entry_node_id);
  return entry?.public_ports?.[connection.protocol] || DEFAULT_PUBLIC_PORTS[connection.protocol];
};

export const ConnectionEditor = ({
  connections,
  onChange,
  clusterNodes,
  mode,
  selectedConnectionId,
  onSelectConnection,
  nodeLinks,
  onConfigureIngress,
}: {
  connections: ConnectionDraft[];
  onChange: (connections: ConnectionDraft[]) => void;
  clusterNodes: SingBoxNode[];
  mode: "graph" | "table";
  selectedConnectionId?: string;
  onSelectConnection: (clientId: string) => void;
  nodeLinks: SingBoxNodeLink[];
  onConfigureIngress: (nodeId: number, protocol: SingBoxProtocol) => void;
}) => {
  const [newProtocol, setNewProtocol] = useState<SingBoxProtocol>("hysteria2");
  const canvasBg = useColorModeValue("#f8fafc", "#111827");
  const edgeLabelColor = useColorModeValue("#334155", "#cbd5e1");
  const flowColorMode = useColorModeValue("light", "dark") as "light" | "dark";
  const selectedConnection = connections.find((connection) => connection.clientId === selectedConnectionId);
  const selectedPort = selectedConnection ? connectionPort(selectedConnection, clusterNodes) : 0;
  const initialNodes = useMemo<Node[]>(() => {
    if (!selectedConnection) return [];
    const entry = clusterNodes.find((node) => node.id === selectedConnection.entry_node_id);
    const exit = selectedConnection.exit_node_id
      ? clusterNodes.find((node) => node.id === selectedConnection.exit_node_id)
      : undefined;
    if (!entry) return [];
    return [
      {
        id: "entry-point",
        type: "topology",
        position: { x: 20, y: 180 },
        data: { label: "ENTRY", host: "Client ingress", kind: "endpoint", endpoint: "entry", acceptsInput: false, emitsOutput: true },
      },
      {
        id: "entry-server",
        type: "topology",
        position: { x: 320, y: 180 },
        data: { label: entry.name, host: entry.public_host, kind: "server", acceptsInput: true, emitsOutput: true, status: entry.status },
      },
      ...(exit ? [{
        id: "exit-server",
        type: "topology",
        position: { x: 650, y: 180 },
        data: { label: exit.name, host: exit.public_host, kind: "server", acceptsInput: true, emitsOutput: true, status: exit.status },
      }] : []),
      {
        id: "exit-point",
        type: "topology",
        position: { x: exit ? 950 : 650, y: 180 },
        data: { label: "EXIT", host: "Public internet", kind: "endpoint", endpoint: "exit", acceptsInput: true, emitsOutput: false },
      },
    ];
  }, [clusterNodes, selectedConnection]);
  const [flowNodes, setFlowNodes, onNodesChange] = useNodesState(initialNodes);
  useEffect(() => setFlowNodes(initialNodes), [initialNodes, setFlowNodes]);

  const edges = useMemo<Edge[]>(() => {
    if (!selectedConnection) return [];
    const color = selectedConnection.enabled ? "#2563eb" : "#94a3b8";
    const link = selectedConnection.exit_node_id
      ? nodeLinks.find((item) => item.enabled && item.from_node_id === selectedConnection.entry_node_id && item.to_node_id === selectedConnection.exit_node_id)
      : undefined;
    const exitNode = selectedConnection.exit_node_id
      ? clusterNodes.find((node) => node.id === selectedConnection.exit_node_id)
      : undefined;
    const linkLabel = link
      ? `${link.protocol}:${exitNode?.node_link_port || "?"}${link.mtls_enabled ? " / mTLS" : ""}`
      : "link unavailable";
    const edge = (id: string, source: string, target: string, label: string): Edge => ({
      id,
      source,
      sourceHandle: "out",
      target,
      targetHandle: "in",
      label,
      animated: selectedConnection.enabled,
      markerEnd: { type: MarkerType.ArrowClosed, color },
      style: { stroke: color, strokeWidth: 2 },
      labelStyle: { fill: edgeLabelColor, fontSize: 11 },
    });
    return selectedConnection.exit_node_id
      ? [
          edge("public-entry", "entry-point", "entry-server", `${selectedConnection.protocol}:${connectionPort(selectedConnection, clusterNodes)}`),
          edge("node-link", "entry-server", "exit-server", linkLabel),
          edge("public-exit", "exit-server", "exit-point", "egress"),
        ]
      : [
          edge("public-entry", "entry-point", "entry-server", `${selectedConnection.protocol}:${connectionPort(selectedConnection, clusterNodes)}`),
          edge("direct-exit", "entry-server", "exit-point", "Direct"),
        ];
  }, [clusterNodes, edgeLabelColor, nodeLinks, selectedConnection]);

  const addConnection = (entryId?: number, exitId?: number | null) => {
    const entry = clusterNodes.find((node) => node.id === (entryId || clusterNodes.find((node) => node.entry_enabled)?.id));
    if (!entry) return;
    const exit = exitId ? clusterNodes.find((node) => node.id === exitId) : undefined;
    const clientId = tempId();
    onChange([
      ...connections,
      {
        clientId,
        label: defaultLabel(entry, exit, newProtocol),
        protocol: newProtocol,
        entry_node_id: entry.id,
        exit_node_id: exit?.id || null,
        enabled: true,
        sort_order: (connections.length + 1) * 100,
      },
    ]);
    onSelectConnection(clientId);
  };

  const update = (clientId: string, patch: Partial<ConnectionDraft>) =>
    onChange(connections.map((connection) => connection.clientId === clientId ? { ...connection, ...patch } : connection));

  if (mode === "graph") {
    if (!selectedConnection) {
      return <Box py={12} textAlign="center" color="gray.500">No connection selected.</Box>;
    }
    return (
      <VStack align="stretch" spacing={3}>
        <HStack align="start" spacing={3} flexWrap="wrap">
          <FormControl maxW="220px"><FormLabel fontSize="xs">Connection</FormLabel><Select size="sm" value={selectedConnection.clientId} onChange={(event) => onSelectConnection(event.target.value)}>{connections.map((connection) => <option key={connection.clientId} value={connection.clientId}>{connection.label}</option>)}</Select></FormControl>
          <FormControl maxW="160px"><FormLabel fontSize="xs">Protocol</FormLabel><Select size="sm" value={selectedConnection.protocol} onChange={(event) => update(selectedConnection.clientId, { protocol: event.target.value as SingBoxProtocol })}>{SINGBOX_PROTOCOLS.map((protocol) => <option key={protocol}>{protocol}</option>)}</Select></FormControl>
          <FormControl maxW="180px"><FormLabel fontSize="xs">Entry</FormLabel><Select size="sm" value={selectedConnection.entry_node_id} onChange={(event) => update(selectedConnection.clientId, { entry_node_id: Number(event.target.value) })}>{clusterNodes.filter((node) => node.entry_enabled).map((node) => <option key={node.id} value={node.id}>{node.name}</option>)}</Select></FormControl>
          <FormControl maxW="190px"><FormLabel fontSize="xs">Ingress profile</FormLabel><HStack><Input size="sm" isReadOnly value={`${selectedConnection.protocol}:${selectedPort}`} fontFamily="mono" /><Button aria-label="Configure ingress profile" size="sm" variant="outline" onClick={() => onConfigureIngress(selectedConnection.entry_node_id, selectedConnection.protocol)}><Cog6ToothIcon width="16px" /></Button></HStack></FormControl>
          <FormControl maxW="180px"><FormLabel fontSize="xs">Exit</FormLabel><Select size="sm" value={selectedConnection.exit_node_id || ""} onChange={(event) => update(selectedConnection.clientId, { exit_node_id: event.target.value ? Number(event.target.value) : null })}><option value="">Direct</option>{clusterNodes.filter((node) => node.exit_enabled && node.id !== selectedConnection.entry_node_id).map((node) => <option key={node.id} value={node.id}>{node.name}</option>)}</Select></FormControl>
        </HStack>
        <Box h="520px" border="1px solid" borderColor="gray.200" _dark={{ borderColor: "gray.700" }}>
          <ReactFlow
            key={`${selectedConnection.clientId}-${selectedConnection.entry_node_id}-${selectedConnection.exit_node_id || "direct"}-${flowNodes.length}`}
            nodes={flowNodes}
            edges={edges}
            nodeTypes={nodeTypes}
            onNodesChange={onNodesChange}
            onEdgeClick={(_, edge) => { if (edge.id === "public-entry") onConfigureIngress(selectedConnection.entry_node_id, selectedConnection.protocol); }}
            fitView
            fitViewOptions={{ padding: 0.18 }}
            minZoom={0.35}
            maxZoom={1.5}
            colorMode={flowColorMode}
          >
            <Background color={useColorModeValue("#cbd5e1", "#334155")} bgColor={canvasBg} gap={20} size={1} />
            <Controls showInteractive={false} />
          </ReactFlow>
        </Box>
      </VStack>
    );
  }

  return (
    <VStack align="stretch" spacing={3}>
      <HStack justify="space-between">
        <FormControl maxW="180px"><FormLabel fontSize="xs">Protocol</FormLabel><Select size="sm" value={newProtocol} onChange={(event) => setNewProtocol(event.target.value as SingBoxProtocol)}>{SINGBOX_PROTOCOLS.map((protocol) => <option key={protocol}>{protocol}</option>)}</Select></FormControl>
        <Button size="sm" mt={5} leftIcon={<PlusIcon width="16px" />} onClick={() => addConnection()}>Add connection</Button>
      </HStack>
      <TableContainer display={{ base: "none", md: "block" }} bg="white" _dark={{ bg: "gray.800" }}>
        <Table size="sm">
          <Thead><Tr><Th>Enabled</Th><Th>Name</Th><Th>Protocol</Th><Th>Entry</Th><Th>Port</Th><Th>Exit</Th><Th /></Tr></Thead>
          <Tbody>
            {connections.map((connection) => (
              <Tr key={connection.clientId} className="interactive" bg={connection.clientId === selectedConnectionId ? "blue.50" : undefined} _dark={{ bg: connection.clientId === selectedConnectionId ? "gray.700" : undefined }} onClick={() => onSelectConnection(connection.clientId)}>
                <Td><Checkbox isChecked={connection.enabled} onChange={(event) => update(connection.clientId, { enabled: event.target.checked })} /></Td>
                <Td><Input minW="190px" size="xs" value={connection.label} onChange={(event) => update(connection.clientId, { label: event.target.value })} /></Td>
                <Td><Select minW="130px" size="xs" value={connection.protocol} onChange={(event) => update(connection.clientId, { protocol: event.target.value as SingBoxProtocol })}>{SINGBOX_PROTOCOLS.map((protocol) => <option key={protocol}>{protocol}</option>)}</Select></Td>
                <Td><Select minW="130px" size="xs" value={connection.entry_node_id} onChange={(event) => update(connection.clientId, { entry_node_id: Number(event.target.value) })}>{clusterNodes.filter((node) => node.entry_enabled).map((node) => <option key={node.id} value={node.id}>{node.name}</option>)}</Select></Td>
                <Td fontFamily="mono" fontSize="xs">{connectionPort(connection, clusterNodes)}</Td>
                <Td><Select minW="130px" size="xs" value={connection.exit_node_id || ""} onChange={(event) => update(connection.clientId, { exit_node_id: event.target.value ? Number(event.target.value) : null })}><option value="">Direct</option>{clusterNodes.filter((node) => node.exit_enabled && node.id !== connection.entry_node_id).map((node) => <option key={node.id} value={node.id}>{node.name}</option>)}</Select></Td>
                <Td isNumeric><Tooltip label="Delete connection"><Button size="xs" variant="ghost" colorScheme="red" onClick={() => onChange(connections.filter((item) => item.clientId !== connection.clientId))}><TrashIcon width="15px" /></Button></Tooltip></Td>
              </Tr>
            ))}
          </Tbody>
        </Table>
      </TableContainer>
      <VStack display={{ base: "flex", md: "none" }} align="stretch" spacing={3}>
        {connections.map((connection) => (
          <Box key={connection.clientId} p={3} bg="white" border="1px solid" borderColor={connection.clientId === selectedConnectionId ? "primary.400" : "gray.200"} borderRadius="6px" _dark={{ bg: "gray.800", borderColor: connection.clientId === selectedConnectionId ? "primary.300" : "gray.700" }} onClick={() => onSelectConnection(connection.clientId)}>
            <HStack justify="space-between" mb={3}>
              <Checkbox isChecked={connection.enabled} onChange={(event) => update(connection.clientId, { enabled: event.target.checked })}>Enabled</Checkbox>
              <Button size="xs" variant="ghost" colorScheme="red" onClick={() => onChange(connections.filter((item) => item.clientId !== connection.clientId))}><TrashIcon width="15px" /></Button>
            </HStack>
            <VStack align="stretch" spacing={3}>
              <FormControl><FormLabel fontSize="xs">Name</FormLabel><Input size="sm" value={connection.label} onChange={(event) => update(connection.clientId, { label: event.target.value })} /></FormControl>
              <HStack align="start">
                <FormControl><FormLabel fontSize="xs">Protocol</FormLabel><Select size="sm" value={connection.protocol} onChange={(event) => update(connection.clientId, { protocol: event.target.value as SingBoxProtocol })}>{SINGBOX_PROTOCOLS.map((protocol) => <option key={protocol}>{protocol}</option>)}</Select></FormControl>
                <FormControl><FormLabel fontSize="xs">Entry</FormLabel><Select size="sm" value={connection.entry_node_id} onChange={(event) => update(connection.clientId, { entry_node_id: Number(event.target.value) })}>{clusterNodes.filter((node) => node.entry_enabled).map((node) => <option key={node.id} value={node.id}>{node.name}</option>)}</Select></FormControl>
              </HStack>
              <HStack align="end"><FormControl><FormLabel fontSize="xs">Exit</FormLabel><Select size="sm" value={connection.exit_node_id || ""} onChange={(event) => update(connection.clientId, { exit_node_id: event.target.value ? Number(event.target.value) : null })}><option value="">Direct</option>{clusterNodes.filter((node) => node.exit_enabled && node.id !== connection.entry_node_id).map((node) => <option key={node.id} value={node.id}>{node.name}</option>)}</Select></FormControl><Box minW="86px"><Text fontSize="xs" color="gray.500">Port</Text><Text h="40px" pt={2} fontFamily="mono" fontSize="sm">{connectionPort(connection, clusterNodes)}</Text></Box></HStack>
            </VStack>
          </Box>
        ))}
      </VStack>
    </VStack>
  );
};
