import {
  Badge,
  Box,
  Grid,
  GridItem,
  HStack,
  SimpleGrid,
  Skeleton,
  Table,
  TableContainer,
  Tbody,
  Td,
  Text,
  Th,
  Thead,
  Tr,
  VStack,
} from "@chakra-ui/react";
import { PageHeader } from "components/AppShell";
import { useQuery } from "react-query";
import { fetch } from "service/http";
import { SingBoxNode, UserSummary } from "types/SingBox";

type ClusterStatus = {
  public_tls: { insecure: boolean; mode: string };
  node_link_tls: { mtls: boolean; protocol: string };
  node_upgrade: { enabled: boolean; target_image?: string | null };
  nodes: Array<{ id: number; heartbeat_stale: boolean; sync_pending: boolean }>;
};

const Metric = ({ label, value, tone = "gray" }: { label: string; value: number; tone?: string }) => (
  <Box py={4} borderTop="3px solid" borderColor={`${tone}.400`}>
    <Text fontSize="2xl" fontWeight="semibold">
      {value}
    </Text>
    <Text fontSize="sm" color="gray.500">
      {label}
    </Text>
  </Box>
);

const lastSeen = (value?: string | null) => {
  if (!value) return "Never";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "Unknown" : date.toLocaleString();
};

export const Overview = () => {
  const nodes = useQuery(["singbox", "nodes"], () => fetch<SingBoxNode[]>("/singbox/nodes"));
  const users = useQuery(["singbox", "users"], () => fetch<UserSummary[]>("/singbox/users"));
  const status = useQuery(["singbox", "status"], () => fetch<ClusterStatus>("/singbox/status"), {
    refetchInterval: 30000,
  });

  const nodeList = nodes.data || [];
  const userList = users.data || [];
  const statusNodes = status.data?.nodes || [];
  const staleIds = new Set(statusNodes.filter((node) => node.heartbeat_stale).map((node) => node.id));
  const pendingIds = new Set(statusNodes.filter((node) => node.sync_pending).map((node) => node.id));
  const online = nodeList.filter((node) => node.status === "connected" && !staleIds.has(node.id)).length;

  return (
    <VStack align="stretch" spacing={6}>
      <PageHeader title="Overview" />
      <SimpleGrid columns={{ base: 2, lg: 4 }} spacing={6}>
        <Metric label="Nodes online" value={online} tone={online === nodeList.length ? "green" : "orange"} />
        <Metric label="Pending sync" value={pendingIds.size} tone={pendingIds.size ? "orange" : "green"} />
        <Metric label="Active users" value={userList.filter((user) => user.status === "active").length} tone="blue" />
        <Metric label="Connections" value={userList.reduce((total, user) => total + user.connection_count, 0)} tone="cyan" />
      </SimpleGrid>

      <Grid templateColumns={{ base: "1fr", xl: "minmax(0, 1fr) 300px" }} gap={6}>
        <GridItem minW={0}>
          <HStack justify="space-between" mb={3}>
            <Text fontSize="sm" fontWeight="semibold">Node health</Text>
            <Badge colorScheme={status.data?.public_tls.insecure ? "orange" : "green"}>
              TLS {status.data?.public_tls.mode || "unknown"}
            </Badge>
          </HStack>
          {nodes.isLoading ? (
            <Skeleton h="240px" />
          ) : (
            <TableContainer bg="white" _dark={{ bg: "gray.800" }}>
              <Table size="sm">
                <Thead><Tr><Th>Node</Th><Th>Roles</Th><Th>Runtime</Th><Th>Config</Th><Th>Last seen</Th></Tr></Thead>
                <Tbody>
                  {nodeList.map((node) => (
                    <Tr key={node.id}>
                      <Td><Text fontWeight="medium">{node.name}</Text><Text fontSize="xs" color="gray.500">{node.public_host}</Text></Td>
                      <Td><HStack>{node.entry_enabled && <Badge>Entry</Badge>}{node.exit_enabled && <Badge>Exit</Badge>}</HStack></Td>
                      <Td><Badge colorScheme={staleIds.has(node.id) ? "red" : node.status === "connected" ? "green" : "gray"}>{staleIds.has(node.id) ? "stale" : node.status}</Badge></Td>
                      <Td><Badge colorScheme={pendingIds.has(node.id) ? "orange" : "green"}>{pendingIds.has(node.id) ? "pending" : "synced"}</Badge></Td>
                      <Td fontSize="xs" color="gray.500">{lastSeen(node.last_seen_at)}</Td>
                    </Tr>
                  ))}
                </Tbody>
              </Table>
            </TableContainer>
          )}
        </GridItem>
        <GridItem>
          <Text fontSize="sm" fontWeight="semibold" mb={3}>Control plane</Text>
          <VStack align="stretch" spacing={0} bg="white" border="1px solid" borderColor="gray.200" _dark={{ bg: "gray.800", borderColor: "gray.700" }}>
            <HStack justify="space-between" p={3} borderBottom="1px solid" borderColor="inherit"><Text fontSize="sm">Node link</Text><Badge colorScheme={status.data?.node_link_tls.mtls ? "green" : "orange"}>{status.data?.node_link_tls.protocol} mTLS</Badge></HStack>
            <HStack justify="space-between" p={3} borderBottom="1px solid" borderColor="inherit"><Text fontSize="sm">Auto upgrade</Text><Badge colorScheme={status.data?.node_upgrade.enabled ? "green" : "gray"}>{status.data?.node_upgrade.enabled ? "Enabled" : "Disabled"}</Badge></HStack>
            <Box p={3}><Text fontSize="xs" color="gray.500" wordBreak="break-all">{status.data?.node_upgrade.target_image || "No target image"}</Text></Box>
          </VStack>
        </GridItem>
      </Grid>
    </VStack>
  );
};
