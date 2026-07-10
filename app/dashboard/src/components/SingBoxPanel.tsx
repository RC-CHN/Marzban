import {
  Badge,
  Box,
  Button,
  Checkbox,
  Divider,
  FormControl,
  FormLabel,
  Grid,
  GridItem,
  HStack,
  Input,
  Select,
  Switch,
  Table,
  TableContainer,
  Tbody,
  Td,
  Text,
  Textarea,
  Th,
  Thead,
  Tooltip,
  Tr,
  VStack,
  useToast,
} from "@chakra-ui/react";
import {
  ArrowPathIcon,
  BoltIcon,
  LinkIcon,
  PlusIcon,
} from "@heroicons/react/24/outline";
import { fetch } from "service/http";
import { ElementType, FC, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "react-query";
import {
  generateErrorMessage,
  generateSuccessMessage,
} from "utils/toastHandler";

type SingBoxNode = {
  id: number;
  name: string;
  public_host: string;
  entry_enabled: boolean;
  exit_enabled: boolean;
  public_ports?: Partial<SingBoxPublicPorts> | null;
  public_tls_mode: SingBoxTLSMode;
  public_tls_cert_path?: string | null;
  public_tls_key_path?: string | null;
  public_tls_ca_cert_path?: string | null;
  node_link_port: number;
  deploy_method: "manual" | "local" | "ssh";
  status: "connected" | "connecting" | "error" | "disabled";
  version?: string | null;
  message?: string | null;
  sync_enabled?: boolean | null;
  last_config_hash?: string | null;
  applied_config_hash?: string | null;
  last_seen_at?: string | null;
};

type SingBoxTLSMode = "system-ca" | "ip-ca" | "ip-insecure";
type SingBoxProtocol =
  | "hysteria2"
  | "tuic"
  | "anytls"
  | "vmess"
  | "vless"
  | "trojan"
  | "shadowsocks";
type SingBoxPublicPorts = Record<SingBoxProtocol, number>;

type SingBoxLink = {
  id: number;
  from_node_id: number;
  to_node_id: number;
  protocol: string;
  enabled: boolean;
  mtls_enabled: boolean;
};

type SingBoxStatus = {
  public_tls: {
    mode: SingBoxTLSMode | "node-controlled";
    modes: SingBoxTLSMode[];
    insecure: boolean;
    ca_configured: boolean;
  };
  node_link_tls: {
    mode: "internal-ca";
    protocol: "anytls" | "hysteria2";
    address_mode: "ip-or-domain";
    mtls: boolean;
  };
};

type SingBoxEnrollment = {
  node_id: number;
  node_name: string;
  token: string;
  expires_at: string;
  bootstrap_url: string;
  command: string;
};

type SingBoxSubscriptionLinks = {
  token: string;
  singbox: string;
  clash: string;
  v2rayn: string;
};

type SingBoxUserPolicyResponse = {
  username: string;
  enabled_protocols: SingBoxProtocol[];
  exit_node_id?: number | null;
  has_credentials: boolean;
  public_subscription?: SingBoxSubscriptionLinks | null;
};

const QueryKey = "singbox-panel";
const DefaultPublicCaPath = "/etc/marzban-singbox/certs/ca.crt";
const TLSModes: { value: SingBoxTLSMode; label: string }[] = [
  { value: "system-ca", label: "System CA" },
  { value: "ip-ca", label: "IP CA" },
  { value: "ip-insecure", label: "Insecure" },
];
const Protocols = [
  "hysteria2",
  "tuic",
  "anytls",
  "vmess",
  "vless",
  "trojan",
  "shadowsocks",
] as const;
const DefaultPublicPorts: SingBoxPublicPorts = {
  hysteria2: 11001,
  tuic: 11002,
  anytls: 11003,
  vmess: 11004,
  vless: 11005,
  trojan: 11006,
  shadowsocks: 11007,
};

const Icon = ({ as: Component }: { as: ElementType }) => (
  <Component width="16px" height="16px" strokeWidth={2} />
);

const tlsModeLabel = (mode: SingBoxTLSMode | "node-controlled") => {
  if (mode === "ip-ca") return "IP CA";
  if (mode === "ip-insecure") return "insecure";
  if (mode === "node-controlled") return "mixed";
  return "system CA";
};

const isValidPort = (port: number) => Number.isInteger(port) && port >= 1 && port <= 65535;

const publicPortsFor = (node: SingBoxNode): SingBoxPublicPorts => ({
  ...DefaultPublicPorts,
  ...(node.public_ports || {}),
});

const publicPortSummary = (node: SingBoxNode) => {
  const ports = publicPortsFor(node);
  return Protocols.map((protocol) => `${protocol}:${ports[protocol]}`).join(", ");
};

const syncPending = (node: SingBoxNode) =>
  Boolean(node.last_config_hash && node.last_config_hash !== node.applied_config_hash);

const lastSeenLabel = (value?: string | null) => {
  if (!value) return "never";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "unknown";
  return date.toLocaleTimeString();
};

export const SingBoxPanel: FC = () => {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [nodeName, setNodeName] = useState("");
  const [nodeHost, setNodeHost] = useState("");
  const [nodeLinkPort, setNodeLinkPort] = useState(12443);
  const [nodePublicPorts, setNodePublicPorts] =
    useState<SingBoxPublicPorts>(DefaultPublicPorts);
  const [nodeTlsMode, setNodeTlsMode] = useState<SingBoxTLSMode>("system-ca");
  const [nodeCaPath, setNodeCaPath] = useState(DefaultPublicCaPath);
  const [policyUsername, setPolicyUsername] = useState("");
  const [policyEntryNodeId, setPolicyEntryNodeId] = useState("");
  const [policyExitNodeId, setPolicyExitNodeId] = useState("");
  const [policyProtocols, setPolicyProtocols] = useState<SingBoxProtocol[]>([...Protocols]);
  const [enrollmentCommand, setEnrollmentCommand] = useState("");
  const [subscriptionLinks, setSubscriptionLinks] = useState<SingBoxSubscriptionLinks | null>(null);

  const nodesQuery = useQuery({
    queryKey: [QueryKey, "nodes"],
    queryFn: () => fetch<SingBoxNode[]>("/singbox/nodes"),
    refetchOnWindowFocus: false,
  });
  const linksQuery = useQuery({
    queryKey: [QueryKey, "links"],
    queryFn: () => fetch<SingBoxLink[]>("/singbox/links"),
    refetchOnWindowFocus: false,
  });
  const statusQuery = useQuery({
    queryKey: [QueryKey, "status"],
    queryFn: () => fetch<SingBoxStatus>("/singbox/status"),
    refetchOnWindowFocus: false,
  });

  const invalidate = () => {
    queryClient.invalidateQueries([QueryKey, "nodes"]);
    queryClient.invalidateQueries([QueryKey, "links"]);
    queryClient.invalidateQueries([QueryKey, "status"]);
  };
  const subscriptionUrl = (path: string) => {
    const absolute = path.startsWith("http") ? path : `${window.location.origin}${path}`;
    if (!policyEntryNodeId) return absolute;
    const separator = absolute.includes("?") ? "&" : "?";
    return `${absolute}${separator}entry_node_id=${policyEntryNodeId}`;
  };

  const addNode = useMutation(
    () =>
      fetch("/singbox/nodes", {
        method: "POST",
        body: {
          name: nodeName,
          public_host: nodeHost,
          node_link_port: nodeLinkPort,
          public_ports: nodePublicPorts,
          public_tls_mode: nodeTlsMode,
          public_tls_ca_cert_path: nodeTlsMode === "ip-ca" ? nodeCaPath : null,
          rebuild_links: true,
        },
      }),
    {
      onSuccess: () => {
        setNodeName("");
        setNodeHost("");
        setNodeLinkPort(12443);
        setNodePublicPorts(DefaultPublicPorts);
        setNodeTlsMode("system-ca");
        setNodeCaPath(DefaultPublicCaPath);
        invalidate();
        generateSuccessMessage("sing-box node added", toast);
      },
      onError: (e) => {
        generateErrorMessage(e, toast);
      },
    }
  );

  const updateNode = useMutation(
    (node: SingBoxNode) =>
      fetch(`/singbox/nodes/${node.id}`, {
        method: "PUT",
        body: node,
      }),
    {
      onSuccess: () => {
        invalidate();
        generateSuccessMessage("sing-box node updated", toast);
      },
      onError: (e) => {
        generateErrorMessage(e, toast);
      },
    }
  );

  const deployNode = useMutation(
    (node: SingBoxNode) =>
      fetch(`/singbox/nodes/${node.id}/deploy`, {
        method: "POST",
        body: { dry_run: true, apply: false },
      }),
    {
      onSuccess: () => {
        invalidate();
        generateSuccessMessage("sing-box config checked", toast);
      },
      onError: (e) => {
        generateErrorMessage(e, toast);
      },
    }
  );

  const createEnrollment = useMutation(
    (node: SingBoxNode) =>
      fetch<SingBoxEnrollment>(`/singbox/nodes/${node.id}/enrollment`, {
        method: "POST",
        body: { expires_in_seconds: 1800 },
      }),
    {
      onSuccess: (data) => {
        setEnrollmentCommand(data.command);
        generateSuccessMessage("sing-box enrollment created", toast);
      },
      onError: (e) => {
        generateErrorMessage(e, toast);
      },
    }
  );

  const rebuildLinks = useMutation(
    () => fetch("/singbox/links/rebuild", { method: "POST" }),
    {
      onSuccess: () => {
        invalidate();
        generateSuccessMessage("node links rebuilt", toast);
      },
      onError: (e) => {
        generateErrorMessage(e, toast);
      },
    }
  );

  const savePolicy = useMutation(
    () =>
      fetch<SingBoxUserPolicyResponse>(`/singbox/users`, {
        method: "POST",
        body: {
          username: policyUsername,
          exit_node_id: policyExitNodeId ? Number(policyExitNodeId) : null,
          enabled_protocols: policyProtocols,
        },
      }),
    {
      onSuccess: (data) => {
        setSubscriptionLinks(data.public_subscription || null);
        generateSuccessMessage("sing-box user policy saved", toast);
      },
      onError: (e) => {
        generateErrorMessage(e, toast);
      },
    }
  );

  const nodes = nodesQuery.data || [];
  const links = linksQuery.data || [];
  const status = statusQuery.data;
  const nodeTlsModes = Array.from(new Set(nodes.map((node) => node.public_tls_mode)));
  const publicTlsMode = nodeTlsModes.length === 1 ? nodeTlsModes[0] : status?.public_tls.mode;
  const publicTlsLabel = publicTlsMode ? `entry ${tlsModeLabel(publicTlsMode)}` : "entry TLS";
  const nodePortsValid =
    isValidPort(nodeLinkPort) &&
    Protocols.every((protocol) => isValidPort(nodePublicPorts[protocol]));

  return (
    <Box
      w="full"
      border="1px solid"
      borderColor="gray.200"
      _dark={{ borderColor: "gray.700" }}
      borderRadius="4px"
      p={4}
      mt={4}
    >
      <VStack align="stretch" spacing={4}>
        <HStack justify="space-between" align="center">
          <HStack spacing={3}>
            <Text fontSize="md" fontWeight="semibold">
              sing-box
            </Text>
            <Badge colorScheme="purple">runtime</Badge>
            {status && (
              <>
                <Badge colorScheme={status.public_tls.insecure ? "orange" : "green"}>
                  {publicTlsLabel}
                </Badge>
                <Badge colorScheme={status.node_link_tls.mtls ? "green" : "blue"}>
                  {status.node_link_tls.protocol} {status.node_link_tls.mtls ? "mTLS" : "CA"}
                </Badge>
              </>
            )}
            <Badge colorScheme="blue">
              <HStack spacing={1}>
                <Icon as={LinkIcon} />
                <span>{links.length}</span>
              </HStack>
            </Badge>
          </HStack>
          <HStack>
            <Tooltip label="Refresh">
              <Button size="sm" onClick={invalidate} leftIcon={<Icon as={ArrowPathIcon} />}>
                Refresh
              </Button>
            </Tooltip>
            <Tooltip label="Rebuild node links">
              <Button
                size="sm"
                onClick={() => rebuildLinks.mutate()}
                isLoading={rebuildLinks.isLoading}
                leftIcon={<Icon as={LinkIcon} />}
              >
                Links
              </Button>
            </Tooltip>
          </HStack>
        </HStack>

        <Grid templateColumns={{ base: "1fr", lg: "2fr 1fr" }} gap={4}>
          <GridItem>
            <TableContainer>
              <Table size="sm">
                <Thead>
                  <Tr>
                    <Th>Name</Th>
                    <Th>Address</Th>
                    <Th>TLS</Th>
                    <Th>Entry</Th>
                    <Th>Exit</Th>
                    <Th>Ports</Th>
                    <Th>Status</Th>
                    <Th>Hash</Th>
                    <Th />
                  </Tr>
                </Thead>
                <Tbody>
                  {nodes.map((node) => (
                    <Tr key={node.id}>
                      <Td>{node.name}</Td>
                      <Td>{node.public_host}</Td>
                      <Td>
                        <Select
                          size="xs"
                          value={node.public_tls_mode}
                          onChange={(event) => {
                            const mode = event.target.value as SingBoxTLSMode;
                            updateNode.mutate({
                              ...node,
                              public_tls_mode: mode,
                              public_tls_ca_cert_path:
                                mode === "ip-ca"
                                  ? node.public_tls_ca_cert_path || DefaultPublicCaPath
                                  : node.public_tls_ca_cert_path,
                            });
                          }}
                        >
                          {TLSModes.map((mode) => (
                            <option key={mode.value} value={mode.value}>
                              {mode.label}
                            </option>
                          ))}
                        </Select>
                      </Td>
                      <Td>
                        <Switch
                          size="sm"
                          isChecked={node.entry_enabled}
                          onChange={(event) =>
                            updateNode.mutate({
                              ...node,
                              entry_enabled: event.target.checked,
                            })
                          }
                        />
                      </Td>
                      <Td>
                        <Switch
                          size="sm"
                          isChecked={node.exit_enabled}
                          onChange={(event) =>
                            updateNode.mutate({
                              ...node,
                              exit_enabled: event.target.checked,
                            })
                          }
                        />
                      </Td>
                      <Td>
                        <Tooltip
                          label={`node-link:${status?.node_link_tls.protocol || "link"}:${node.node_link_port}, ${publicPortSummary(node)}`}
                        >
                          <Text maxW="150px" isTruncated fontFamily="mono" fontSize="xs">
                            {node.node_link_port} / {publicPortsFor(node).hysteria2}-
                            {publicPortsFor(node).shadowsocks}
                          </Text>
                        </Tooltip>
                      </Td>
                      <Td>
                        <VStack align="start" spacing={1}>
                          <Badge colorScheme={node.status === "connected" ? "green" : "gray"}>
                            {node.status}
                          </Badge>
                          <Badge
                            colorScheme={
                              node.sync_enabled ? (syncPending(node) ? "orange" : "green") : "gray"
                            }
                          >
                            {node.sync_enabled ? (syncPending(node) ? "pending" : "synced") : "manual"}
                          </Badge>
                          <Tooltip label={node.message || node.version || ""}>
                            <Text maxW="120px" isTruncated fontSize="xs" color="gray.500">
                              {lastSeenLabel(node.last_seen_at)}
                            </Text>
                          </Tooltip>
                        </VStack>
                      </Td>
                      <Td>
                        <Tooltip label={node.applied_config_hash || node.last_config_hash || ""}>
                          <Text maxW="120px" isTruncated fontFamily="mono" fontSize="xs">
                            {node.applied_config_hash || node.last_config_hash || "-"}
                          </Text>
                        </Tooltip>
                      </Td>
                      <Td isNumeric>
                        <HStack justify="flex-end" spacing={2}>
                          <Tooltip label="Create enrollment command">
                            <Button
                              size="xs"
                              onClick={() => createEnrollment.mutate(node)}
                              isLoading={createEnrollment.isLoading}
                              leftIcon={<Icon as={LinkIcon} />}
                            >
                              Enroll
                            </Button>
                          </Tooltip>
                          <Tooltip label="Dry-run deploy">
                            <Button
                              size="xs"
                              onClick={() => deployNode.mutate(node)}
                              isLoading={deployNode.isLoading}
                              leftIcon={<Icon as={BoltIcon} />}
                            >
                              Check
                            </Button>
                          </Tooltip>
                        </HStack>
                      </Td>
                    </Tr>
                  ))}
                </Tbody>
              </Table>
            </TableContainer>
          </GridItem>

          <GridItem>
            <VStack align="stretch" spacing={3}>
              <Text fontSize="sm" fontWeight="medium">
                Add node
              </Text>
              <Grid templateColumns={{ base: "1fr", xl: "repeat(4, minmax(0, 1fr))" }} gap={2}>
                <FormControl>
                  <FormLabel fontSize="xs">Name</FormLabel>
                  <Input size="sm" value={nodeName} onChange={(e) => setNodeName(e.target.value)} />
                </FormControl>
                <FormControl>
                  <FormLabel fontSize="xs">Address</FormLabel>
                  <Input
                    size="sm"
                    placeholder="IP or DNS"
                    value={nodeHost}
                    onChange={(e) => setNodeHost(e.target.value)}
                  />
                </FormControl>
                <FormControl>
                  <FormLabel fontSize="xs">TLS</FormLabel>
                  <Select
                    size="sm"
                    value={nodeTlsMode}
                    onChange={(e) => setNodeTlsMode(e.target.value as SingBoxTLSMode)}
                  >
                    {TLSModes.map((mode) => (
                      <option key={mode.value} value={mode.value}>
                        {mode.label}
                      </option>
                    ))}
                  </Select>
                </FormControl>
                <FormControl>
                  <FormLabel fontSize="xs">Link port</FormLabel>
                  <Input
                    size="sm"
                    type="number"
                    min={1}
                    max={65535}
                    value={nodeLinkPort}
                    onChange={(e) => setNodeLinkPort(Number(e.target.value))}
                  />
                </FormControl>
                {nodeTlsMode === "ip-ca" && (
                  <FormControl>
                    <FormLabel fontSize="xs">CA path</FormLabel>
                    <Input
                      size="sm"
                      value={nodeCaPath}
                      onChange={(e) => setNodeCaPath(e.target.value)}
                    />
                  </FormControl>
                )}
              </Grid>
              <Grid templateColumns={{ base: "repeat(2, minmax(0, 1fr))", xl: "repeat(4, minmax(0, 1fr))" }} gap={2}>
                {Protocols.map((protocol) => (
                  <FormControl key={protocol}>
                    <FormLabel fontSize="xs">{protocol}</FormLabel>
                    <Input
                      size="sm"
                      type="number"
                      min={1}
                      max={65535}
                      value={nodePublicPorts[protocol]}
                      onChange={(e) =>
                        setNodePublicPorts((current) => ({
                          ...current,
                          [protocol]: Number(e.target.value),
                        }))
                      }
                    />
                  </FormControl>
                ))}
              </Grid>
              <HStack justify="flex-end">
                <Button
                  size="sm"
                  onClick={() => addNode.mutate()}
                  isDisabled={
                    !nodeName ||
                    !nodeHost ||
                    !nodePortsValid ||
                    (nodeTlsMode === "ip-ca" && !nodeCaPath)
                  }
                  isLoading={addNode.isLoading}
                  leftIcon={<Icon as={PlusIcon} />}
                >
                  Add
                </Button>
              </HStack>

              {enrollmentCommand && (
                <>
                  <Divider />
                  <FormControl>
                    <FormLabel fontSize="xs">Enrollment command</FormLabel>
                    <Textarea
                      size="sm"
                      value={enrollmentCommand}
                      isReadOnly
                      fontFamily="mono"
                      fontSize="xs"
                      rows={4}
                    />
                  </FormControl>
                </>
              )}

              <Divider />

              <Text fontSize="sm" fontWeight="medium">
                User route
              </Text>
              <HStack align="flex-end">
                <FormControl>
                  <FormLabel fontSize="xs">Username</FormLabel>
                  <Input
                    size="sm"
                    value={policyUsername}
                    onChange={(e) => setPolicyUsername(e.target.value)}
                  />
                </FormControl>
                <FormControl>
                  <FormLabel fontSize="xs">Entry</FormLabel>
                  <Select
                    size="sm"
                    value={policyEntryNodeId}
                    onChange={(e) => setPolicyEntryNodeId(e.target.value)}
                  >
                    <option value="">Auto</option>
                    {nodes
                      .filter((node) => node.entry_enabled)
                      .map((node) => (
                        <option key={node.id} value={node.id}>
                          {node.name}
                        </option>
                      ))}
                  </Select>
                </FormControl>
                <FormControl>
                  <FormLabel fontSize="xs">Exit</FormLabel>
                  <Select
                    size="sm"
                    value={policyExitNodeId}
                    onChange={(e) => setPolicyExitNodeId(e.target.value)}
                  >
                    <option value="">Direct</option>
                    {nodes
                      .filter((node) => node.exit_enabled)
                      .map((node) => (
                        <option key={node.id} value={node.id}>
                          {node.name}
                        </option>
                      ))}
                  </Select>
                </FormControl>
                <Button
                  size="sm"
                  onClick={() => savePolicy.mutate()}
                  isDisabled={!policyUsername}
                  isLoading={savePolicy.isLoading}
                >
                  Save
                </Button>
              </HStack>
              <Grid templateColumns="repeat(2, minmax(0, 1fr))" gap={2}>
                {Protocols.map((protocol) => (
                  <Checkbox
                    key={protocol}
                    size="sm"
                    isChecked={policyProtocols.includes(protocol)}
                    onChange={(event) => {
                      setPolicyProtocols((current) =>
                        event.target.checked
                          ? [...new Set([...current, protocol])]
                          : current.filter((item) => item !== protocol)
                      );
                    }}
                  >
                    {protocol}
                </Checkbox>
              ))}
              </Grid>
              {subscriptionLinks && (
                <>
                  <Divider />
                  <FormControl>
                    <FormLabel fontSize="xs">sing-box subscription</FormLabel>
                    <Input size="sm" value={subscriptionUrl(subscriptionLinks.singbox)} isReadOnly />
                  </FormControl>
                  <FormControl>
                    <FormLabel fontSize="xs">Clash subscription</FormLabel>
                    <Input size="sm" value={subscriptionUrl(subscriptionLinks.clash)} isReadOnly />
                  </FormControl>
                  <FormControl>
                    <FormLabel fontSize="xs">v2rayN subscription</FormLabel>
                    <Input size="sm" value={subscriptionUrl(subscriptionLinks.v2rayn)} isReadOnly />
                  </FormControl>
                </>
              )}
            </VStack>
          </GridItem>
        </Grid>
      </VStack>
    </Box>
  );
};
