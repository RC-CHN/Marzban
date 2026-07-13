import {
  Badge,
  Box,
  Button,
  HStack,
  IconButton,
  Tab,
  TabList,
  TabPanel,
  TabPanels,
  Table,
  TableContainer,
  Tbody,
  Td,
  Text,
  Th,
  Thead,
  Tooltip,
  Tr,
  Tabs,
} from "@chakra-ui/react";
import { Cog6ToothIcon, PencilSquareIcon, PlusIcon } from "@heroicons/react/24/outline";
import { useTranslation } from "react-i18next";
import { Adjacency, NetworkDraft, NetworkWorkspace } from "types/SingBox";

type ResourceKind = "ingress" | "egress" | "adjacency" | "policy";

type Props = {
  draft: NetworkDraft;
  workspace: NetworkWorkspace;
  selected?: { kind: string; index?: number; nodeId?: number } | null;
  onSelect: (kind: ResourceKind, index: number) => void;
  onManageServer: (nodeId: number) => void;
  onAddServer: () => void;
  onAddIngress: () => void;
  onAddEgress: () => void;
  onAddAdjacency: () => void;
  onAddPolicy: () => void;
};

const stateColor = (state?: string) => {
  if (state === "up" || state === "connected") return "green";
  if (state === "down" || state === "error") return "red";
  if (state === "provisioning" || state === "connecting") return "orange";
  return "gray";
};

const ingressState = (item: NetworkDraft["ingresses"][number], observed?: NetworkWorkspace["ingresses"][number]) => {
  if (!item.enabled) return "disabled";
  if (!observed) return item.id ? "unknown" : "new";
  const pending = item.node_id !== observed.node_id
    || item.advertised_address_id !== observed.advertised_address_id
    || item.protocol !== observed.protocol
    || item.listen_port !== observed.listen_port
    || item.tls_mode !== observed.tls_mode
    || JSON.stringify(item.tls_profile) !== JSON.stringify(observed.tls_profile)
    || JSON.stringify(item.protocol_profile) !== JSON.stringify(observed.protocol_profile);
  return pending ? "provisioning" : observed.oper_state || "unknown";
};

const adjacencyState = (adjacency: Adjacency, observed?: Adjacency) => {
  if (!adjacency.enabled) return "disabled";
  if (!observed) return adjacency.id ? "unknown" : "new";
  const pending = adjacency.node_a_id !== observed.node_a_id
    || adjacency.node_b_id !== observed.node_b_id
    || adjacency.enabled !== observed.enabled
    || adjacency.directions.some((direction) => {
      const current = observed.directions.find((item) => item.id === direction.id);
      return !current
        || direction.enabled !== current.enabled
        || direction.transport !== current.transport
        || direction.listen_port !== current.listen_port
        || direction.admin_cost !== current.admin_cost
        || JSON.stringify(direction.settings) !== JSON.stringify(current.settings);
    });
  if (pending) return "provisioning";
  const states = observed.directions.map((item) => item.oper_state || "unknown");
  if (states.includes("down")) return "down";
  if (states.length && states.every((state) => state === "up")) return "up";
  return "unknown";
};

const ResourceHeader = ({ title, count, action, onAdd }: { title: string; count: number; action: string; onAdd: () => void }) => (
  <HStack justify="space-between" mb={3}>
    <Box>
      <Text fontSize="sm" fontWeight="semibold">{title}</Text>
      <Text fontSize="xs" color="gray.500"><ConfiguredCount count={count} /></Text>
    </Box>
    <Button size="sm" leftIcon={<PlusIcon width="15px" />} onClick={onAdd}>{action}</Button>
  </HStack>
);

const ConfiguredCount = ({ count }: { count: number }) => {
  const { t } = useTranslation();
  return <>{t("network.column.configured", { count })}</>;
};

const EditButton = ({ label, onClick }: { label: string; onClick: () => void }) => (
  <Tooltip label={label}>
    <IconButton aria-label={label} size="xs" variant="ghost" icon={<PencilSquareIcon width="15px" />} onClick={onClick} />
  </Tooltip>
);

export const NetworkResourceTables = ({
  draft,
  workspace,
  selected,
  onSelect,
  onManageServer,
  onAddServer,
  onAddIngress,
  onAddEgress,
  onAddAdjacency,
  onAddPolicy,
}: Props) => {
  const { t } = useTranslation();
  const nodeName = (nodeId: number) => workspace.nodes.find((node) => node.id === nodeId)?.name || `Node ${nodeId}`;
  const selectedRow = (kind: string, index: number) => selected?.kind === kind && selected.index === index;
  const stateLabel = (state?: string) => t(`network.state.${state || "unknown"}`, { defaultValue: state || t("network.state.unknown") });

  return (
    <Tabs variant="line" colorScheme="primary" isLazy>
      <TabList overflowX="auto" overflowY="hidden">
        <Tab fontSize="sm">{t("network.resource.servers")}</Tab>
        <Tab fontSize="sm">{t("network.resource.ingresses")}</Tab>
        <Tab fontSize="sm">{t("network.resource.egresses")}</Tab>
        <Tab fontSize="sm">{t("network.resource.adjacencies")}</Tab>
        <Tab fontSize="sm">{t("network.resource.policies")}</Tab>
      </TabList>
      <TabPanels>
        <TabPanel px={0}>
          <ResourceHeader title={t("network.resource.servers")} count={workspace.nodes.length} action={t("network.action.addServer")} onAdd={onAddServer} />
          <TableContainer border="1px solid" borderColor="gray.200" _dark={{ borderColor: "gray.700" }}>
            <Table size="sm">
              <Thead><Tr><Th>{t("network.column.server")}</Th><Th>{t("network.column.status")}</Th><Th>{t("network.column.ingresses")}</Th><Th>{t("network.column.egresses")}</Th><Th /></Tr></Thead>
              <Tbody>{workspace.nodes.map((node) => <Tr key={node.id} bg={selected?.kind === "server" && selected.nodeId === node.id ? "gray.50" : undefined} _dark={{ bg: selected?.kind === "server" && selected.nodeId === node.id ? "gray.700" : undefined }}>
                <Td><Text fontWeight="medium">{node.name}</Text><Text fontSize="xs" color="gray.500" fontFamily="mono">{node.public_host}</Text></Td>
                <Td><Badge colorScheme={stateColor(node.status)}>{stateLabel(node.status)}</Badge></Td>
                <Td>{draft.ingresses.filter((item) => item.node_id === node.id).length}</Td>
                <Td>{draft.egresses.filter((item) => item.node_id === node.id).length}</Td>
                <Td isNumeric><Tooltip label={t("network.action.manageServer", { name: node.name })}><IconButton aria-label={t("network.action.manageServer", { name: node.name })} size="xs" variant="ghost" icon={<Cog6ToothIcon width="15px" />} onClick={() => onManageServer(node.id)} /></Tooltip></Td>
              </Tr>)}</Tbody>
            </Table>
          </TableContainer>
        </TabPanel>

        <TabPanel px={0}>
          <ResourceHeader title={t("network.resource.ingresses")} count={draft.ingresses.length} action={t("network.action.addIngress")} onAdd={onAddIngress} />
          <TableContainer border="1px solid" borderColor="gray.200" _dark={{ borderColor: "gray.700" }}>
            <Table size="sm">
              <Thead><Tr><Th>{t("network.column.name")}</Th><Th>{t("network.column.server")}</Th><Th>{t("network.column.listener")}</Th><Th>{t("network.column.tls")}</Th><Th>{t("network.column.status")}</Th><Th /></Tr></Thead>
              <Tbody>{draft.ingresses.map((item, index) => {
                const observed = workspace.ingresses.find((value) => value.id === item.id);
                const state = ingressState(item, observed);
                return <Tr key={item.id || `ingress-${index}`} cursor="pointer" onClick={() => onSelect("ingress", index)} bg={selectedRow("ingress", index) ? "gray.50" : undefined} _dark={{ bg: selectedRow("ingress", index) ? "gray.700" : undefined }}>
                  <Td fontWeight="medium">{item.name}</Td><Td>{nodeName(item.node_id)}</Td><Td fontFamily="mono">{item.protocol}:{item.listen_port}</Td><Td>{item.tls_mode}</Td><Td><Badge colorScheme={stateColor(state)}>{stateLabel(state)}</Badge></Td><Td isNumeric><EditButton label={t("network.action.editIngress", { name: item.name })} onClick={() => onSelect("ingress", index)} /></Td>
                </Tr>;
              })}</Tbody>
            </Table>
          </TableContainer>
        </TabPanel>

        <TabPanel px={0}>
          <ResourceHeader title={t("network.resource.directEgresses")} count={draft.egresses.length} action={t("network.action.addEgress")} onAdd={onAddEgress} />
          <TableContainer border="1px solid" borderColor="gray.200" _dark={{ borderColor: "gray.700" }}>
            <Table size="sm">
              <Thead><Tr><Th>{t("network.column.name")}</Th><Th>{t("network.column.server")}</Th><Th>{t("network.column.kind")}</Th><Th>{t("network.column.status")}</Th><Th /></Tr></Thead>
              <Tbody>{draft.egresses.map((item, index) => <Tr key={item.id || `egress-${index}`} cursor="pointer" onClick={() => onSelect("egress", index)} bg={selectedRow("egress", index) ? "gray.50" : undefined} _dark={{ bg: selectedRow("egress", index) ? "gray.700" : undefined }}>
                <Td fontWeight="medium">{item.name}</Td><Td>{nodeName(item.node_id)}</Td><Td>{t("network.option.direct")}</Td><Td><Badge colorScheme={item.enabled ? "green" : "gray"}>{stateLabel(item.enabled ? "enabled" : "disabled")}</Badge></Td><Td isNumeric><EditButton label={t("network.action.editEgress", { name: item.name })} onClick={() => onSelect("egress", index)} /></Td>
              </Tr>)}</Tbody>
            </Table>
          </TableContainer>
        </TabPanel>

        <TabPanel px={0}>
          <ResourceHeader title={t("network.resource.adjacencies")} count={draft.adjacencies.length} action={t("network.action.addAdjacency")} onAdd={onAddAdjacency} />
          <TableContainer border="1px solid" borderColor="gray.200" _dark={{ borderColor: "gray.700" }}>
            <Table size="sm">
              <Thead><Tr><Th>{t("network.column.name")}</Th><Th>{t("network.column.endpoints")}</Th><Th>{t("network.column.directions")}</Th><Th>{t("network.field.cost")}</Th><Th>{t("network.column.status")}</Th><Th /></Tr></Thead>
              <Tbody>{draft.adjacencies.map((item, index) => {
                const observed = workspace.adjacencies.find((value) => value.id === item.id);
                const state = adjacencyState(item, observed);
                return <Tr key={item.id || `adjacency-${index}`} cursor="pointer" onClick={() => onSelect("adjacency", index)} bg={selectedRow("adjacency", index) ? "gray.50" : undefined} _dark={{ bg: selectedRow("adjacency", index) ? "gray.700" : undefined }}>
                  <Td fontWeight="medium">{item.name}</Td><Td>{nodeName(item.node_a_id)} / {nodeName(item.node_b_id)}</Td><Td>{item.directions.filter((direction) => direction.enabled).length}</Td><Td>{item.directions.map((direction) => direction.admin_cost).join(" / ")}</Td><Td><Badge colorScheme={stateColor(state)}>{stateLabel(state)}</Badge></Td><Td isNumeric><EditButton label={t("network.action.editAdjacency", { name: item.name })} onClick={() => onSelect("adjacency", index)} /></Td>
                </Tr>;
              })}</Tbody>
            </Table>
          </TableContainer>
        </TabPanel>

        <TabPanel px={0}>
          <ResourceHeader title={t("network.resource.policies")} count={draft.routing_policies.length} action={t("network.action.addPolicy")} onAdd={onAddPolicy} />
          <TableContainer border="1px solid" borderColor="gray.200" _dark={{ borderColor: "gray.700" }}>
            <Table size="sm">
              <Thead><Tr><Th>{t("network.column.name")}</Th><Th>{t("network.column.metric")}</Th><Th>{t("network.column.maxHops")}</Th><Th>{t("network.column.failover")}</Th><Th>{t("network.column.constraints")}</Th><Th /></Tr></Thead>
              <Tbody>{draft.routing_policies.map((item, index) => <Tr key={item.id || `policy-${index}`} cursor="pointer" onClick={() => onSelect("policy", index)} bg={selectedRow("policy", index) ? "gray.50" : undefined} _dark={{ bg: selectedRow("policy", index) ? "gray.700" : undefined }}>
                <Td fontWeight="medium">{item.name}</Td><Td>{t("network.option.adminCost")}</Td><Td>{item.max_hops}</Td><Td><Badge colorScheme={item.failover ? "green" : "gray"}>{stateLabel(item.failover ? "enabled" : "disabled")}</Badge></Td><Td>{t("network.policy.constraintSummary", { required: item.required_node_ids.length, avoided: item.avoided_node_ids.length })}</Td><Td isNumeric><EditButton label={t("network.action.editPolicy", { name: item.name })} onClick={() => onSelect("policy", index)} /></Td>
              </Tr>)}</Tbody>
            </Table>
          </TableContainer>
        </TabPanel>
      </TabPanels>
    </Tabs>
  );
};
