import {
  Badge,
  Box,
  Button,
  FormControl,
  FormLabel,
  Grid,
  HStack,
  Input,
  Modal,
  ModalBody,
  ModalCloseButton,
  ModalContent,
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
  Textarea,
  VStack,
  useDisclosure,
  useToast,
} from "@chakra-ui/react";
import { ArrowLeftIcon, ArrowPathIcon, CodeBracketIcon } from "@heroicons/react/24/outline";
import { PageHeader } from "components/AppShell";
import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "react-query";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { fetch } from "service/http";
import {
  AnyTLSSettings,
  DEFAULT_PROTOCOL_SETTINGS,
  DEFAULT_PUBLIC_PORTS,
  Hysteria2Settings,
  ProtocolSettings,
  SINGBOX_PROTOCOLS,
  SingBoxNode,
  SingBoxNodeLink,
  SingBoxProtocol,
  TUICSettings,
} from "types/SingBox";
import { generateErrorMessage, generateSuccessMessage } from "utils/toastHandler";

type Impact = { node_id: number; protocols: Record<SingBoxProtocol, number> };
type GeneratedConfig = { node_id: number; hash: string; config: object };

const cloneDefaults = (): ProtocolSettings => JSON.parse(JSON.stringify(DEFAULT_PROTOCOL_SETTINGS));
const profileIsDefault = (protocol: SingBoxProtocol, settings: ProtocolSettings) => {
  if (!(protocol in DEFAULT_PROTOCOL_SETTINGS)) return true;
  const key = protocol as keyof ProtocolSettings;
  return JSON.stringify(settings[key]) === JSON.stringify(DEFAULT_PROTOCOL_SETTINGS[key]);
};

const NumberField = ({ label, value, onChange }: { label: string; value?: number | null; onChange: (value: number | null) => void }) => (
  <FormControl>
    <FormLabel fontSize="xs">{label}</FormLabel>
    <NumberInput size="sm" min={1} max={100000} value={value ?? ""} onChange={(_, next) => onChange(Number.isFinite(next) ? next : null)}>
      <NumberInputField fontFamily="mono" />
    </NumberInput>
  </FormControl>
);

const Hysteria2Editor = ({ value, onChange }: { value: Hysteria2Settings; onChange: (value: Hysteria2Settings) => void }) => (
  <VStack align="stretch" spacing={5}>
    <Grid templateColumns={{ base: "1fr", md: "1fr 1fr" }} gap={4}>
      <NumberField label="Upload limit (Mbps)" value={value.up_mbps} onChange={(next) => onChange({ ...value, up_mbps: next })} />
      <NumberField label="Download limit (Mbps)" value={value.down_mbps} onChange={(next) => onChange({ ...value, down_mbps: next })} />
    </Grid>
    <FormControl display="flex" alignItems="center" justifyContent="space-between"><FormLabel fontSize="sm" mb={0}>Ignore client bandwidth</FormLabel><Switch isChecked={value.ignore_client_bandwidth} onChange={(event) => onChange({ ...value, ignore_client_bandwidth: event.target.checked })} /></FormControl>
    <Grid templateColumns={{ base: "1fr", md: "180px 1fr" }} gap={4}>
      <FormControl><FormLabel fontSize="xs">Obfuscation</FormLabel><Select size="sm" value={value.obfs_type} onChange={(event) => onChange({ ...value, obfs_type: event.target.value as Hysteria2Settings["obfs_type"] })}><option value="none">Disabled</option><option value="salamander">Salamander</option></Select></FormControl>
      <FormControl isDisabled={value.obfs_type === "none"}><FormLabel fontSize="xs">Obfs password</FormLabel><Input size="sm" type="password" value={value.obfs_password || ""} onChange={(event) => onChange({ ...value, obfs_password: event.target.value || null })} /></FormControl>
    </Grid>
    <FormControl><FormLabel fontSize="xs">Masquerade URL</FormLabel><Input size="sm" placeholder="https://origin.example" value={value.masquerade_url || ""} onChange={(event) => onChange({ ...value, masquerade_url: event.target.value || null })} /></FormControl>
  </VStack>
);

const TUICEditor = ({ value, onChange }: { value: TUICSettings; onChange: (value: TUICSettings) => void }) => (
  <VStack align="stretch" spacing={5}>
    <Grid templateColumns={{ base: "1fr", md: "repeat(3, 1fr)" }} gap={4}>
      <FormControl><FormLabel fontSize="xs">Congestion control</FormLabel><Select size="sm" value={value.congestion_control} onChange={(event) => onChange({ ...value, congestion_control: event.target.value as TUICSettings["congestion_control"] })}><option value="bbr">BBR</option><option value="cubic">Cubic</option><option value="new_reno">New Reno</option></Select></FormControl>
      <FormControl><FormLabel fontSize="xs">Authentication timeout</FormLabel><Input size="sm" fontFamily="mono" value={value.auth_timeout} onChange={(event) => onChange({ ...value, auth_timeout: event.target.value })} /></FormControl>
      <FormControl><FormLabel fontSize="xs">Heartbeat</FormLabel><Input size="sm" fontFamily="mono" value={value.heartbeat} onChange={(event) => onChange({ ...value, heartbeat: event.target.value })} /></FormControl>
    </Grid>
    <FormControl display="flex" alignItems="center" justifyContent="space-between"><Box><FormLabel fontSize="sm" mb={0}>0-RTT handshake</FormLabel><Text fontSize="xs" color="orange.500">Replay-sensitive; keep disabled unless required.</Text></Box><Switch colorScheme="orange" isChecked={value.zero_rtt_handshake} onChange={(event) => onChange({ ...value, zero_rtt_handshake: event.target.checked })} /></FormControl>
  </VStack>
);

const AnyTLSEditor = ({ value, onChange }: { value: AnyTLSSettings; onChange: (value: AnyTLSSettings) => void }) => (
  <VStack align="stretch" spacing={5}>
    <Grid templateColumns={{ base: "1fr", md: "repeat(3, 1fr)" }} gap={4}>
      <FormControl><FormLabel fontSize="xs">Idle check interval</FormLabel><Input size="sm" fontFamily="mono" value={value.idle_session_check_interval} onChange={(event) => onChange({ ...value, idle_session_check_interval: event.target.value })} /></FormControl>
      <FormControl><FormLabel fontSize="xs">Idle timeout</FormLabel><Input size="sm" fontFamily="mono" value={value.idle_session_timeout} onChange={(event) => onChange({ ...value, idle_session_timeout: event.target.value })} /></FormControl>
      <FormControl><FormLabel fontSize="xs">Minimum idle sessions</FormLabel><NumberInput size="sm" min={0} max={1024} value={value.min_idle_session} onChange={(_, next) => onChange({ ...value, min_idle_session: next })}><NumberInputField fontFamily="mono" /></NumberInput></FormControl>
    </Grid>
    <FormControl><FormLabel fontSize="xs">Padding scheme</FormLabel><Textarea minH="170px" fontFamily="mono" fontSize="xs" placeholder="Leave empty for sing-box defaults" value={(value.padding_scheme || []).join("\n")} onChange={(event) => onChange({ ...value, padding_scheme: event.target.value.trim() ? event.target.value.split("\n") : null })} /></FormControl>
  </VStack>
);

export const NodeDetails = () => {
  const { nodeId = "" } = useParams();
  const id = Number(nodeId);
  const [searchParams] = useSearchParams();
  const requestedProtocol = searchParams.get("protocol") as SingBoxProtocol | null;
  const [selectedProtocol, setSelectedProtocol] = useState<SingBoxProtocol>(SINGBOX_PROTOCOLS.includes(requestedProtocol as SingBoxProtocol) ? requestedProtocol as SingBoxProtocol : "hysteria2");
  const [ports, setPorts] = useState({ ...DEFAULT_PUBLIC_PORTS });
  const [settings, setSettings] = useState<ProtocolSettings>(cloneDefaults());
  const navigate = useNavigate();
  const toast = useToast();
  const configModal = useDisclosure();
  const queryClient = useQueryClient();
  const nodes = useQuery(["singbox", "nodes"], () => fetch<SingBoxNode[]>("/singbox/nodes"));
  const links = useQuery(["singbox", "links"], () => fetch<SingBoxNodeLink[]>("/singbox/links"));
  const impact = useQuery(["singbox", "node-impact", id], () => fetch<Impact>(`/singbox/nodes/${id}/protocol-impact`), { enabled: Boolean(id) });
  const generated = useQuery(["singbox", "node-config", id], () => fetch<GeneratedConfig>(`/singbox/nodes/${id}/config`), { enabled: false });
  const node = nodes.data?.find((item) => item.id === id);
  useEffect(() => {
    if (!node) return;
    setPorts({ ...DEFAULT_PUBLIC_PORTS, ...(node.public_ports || {}) });
    setSettings({ ...cloneDefaults(), ...(node.protocol_settings || {}) });
  }, [node]);
  const save = useMutation(
    () => fetch<SingBoxNode>(`/singbox/nodes/${id}`, { method: "PUT", body: { public_ports: ports, protocol_settings: settings } }),
    {
      onSuccess: () => {
        queryClient.invalidateQueries(["singbox", "nodes"]);
        queryClient.invalidateQueries(["singbox", "node-config", id]);
        generateSuccessMessage("Ingress profile applied", toast);
      },
      onError: (error) => { generateErrorMessage(error, toast); },
    }
  );
  const relatedLinks = useMemo(() => (links.data || []).filter((link) => link.from_node_id === id || link.to_node_id === id), [id, links.data]);
  const openConfig = async () => { await generated.refetch(); configModal.onOpen(); };
  if (nodes.isLoading) return <Skeleton h="500px" />;
  if (!node) return <Text py={8}>Node not found.</Text>;
  const pending = Boolean(node.last_config_hash && node.last_config_hash !== node.applied_config_hash);
  const selectedIsDefault = profileIsDefault(selectedProtocol, settings);

  return (
    <VStack align="stretch" spacing={5}>
      <PageHeader title={node.name} actions={<HStack><Badge colorScheme={node.status === "connected" ? "green" : "gray"}>{node.status}</Badge><Badge colorScheme={pending ? "orange" : "green"}>{pending ? "Pending" : "Applied"}</Badge></HStack>} />
      <Button alignSelf="start" size="xs" variant="ghost" leftIcon={<ArrowLeftIcon width="14px" />} onClick={() => navigate("/nodes")}>Nodes</Button>
      <Tabs variant="line" colorScheme="primary" isLazy defaultIndex={requestedProtocol ? 1 : 0}>
        <TabList><Tab>Overview</Tab><Tab>Ingress</Tab><Tab>Links</Tab><Tab>Runtime</Tab></TabList>
        <TabPanels>
          <TabPanel px={0}><Grid templateColumns={{ base: "1fr", md: "180px 1fr" }} rowGap={3} fontSize="sm"><Text color="gray.500">Public address</Text><Text fontFamily="mono">{node.public_host}</Text><Text color="gray.500">Public TLS</Text><Text>{node.public_tls_mode}</Text><Text color="gray.500">Node-link port</Text><Text fontFamily="mono">{node.node_link_port}</Text><Text color="gray.500">Last seen</Text><Text>{node.last_seen_at || "Never"}</Text></Grid></TabPanel>
          <TabPanel px={0}>
            <Grid templateColumns={{ base: "1fr", lg: "230px minmax(0, 1fr)" }} gap={6}>
              <VStack align="stretch" spacing={0} borderRight={{ lg: "1px solid" }} borderColor="gray.200" pr={{ lg: 4 }}>
                {SINGBOX_PROTOCOLS.map((protocol) => <Button key={protocol} h="48px" justifyContent="space-between" borderRadius="0" variant={selectedProtocol === protocol ? "solid" : "ghost"} colorScheme={selectedProtocol === protocol ? "primary" : "gray"} onClick={() => setSelectedProtocol(protocol)}><Text>{protocol}</Text><Text fontSize="xs" fontFamily="mono">:{ports[protocol]}</Text></Button>)}
              </VStack>
              <VStack align="stretch" spacing={5} minW={0}>
                <HStack justify="space-between" align="start" flexWrap="wrap"><Box><HStack><Text fontWeight="semibold">{node.name} / {selectedProtocol}</Text><Badge colorScheme={selectedIsDefault ? "gray" : "blue"}>{selectedIsDefault ? "Default" : "Node override"}</Badge></HStack><Text fontSize="xs" color="gray.500">Shared by {impact.data?.protocols[selectedProtocol] || 0} active connections</Text></Box><HStack><Button size="sm" variant="ghost" leftIcon={<ArrowPathIcon width="15px" />} onClick={() => { if (selectedProtocol in DEFAULT_PROTOCOL_SETTINGS) { const key = selectedProtocol as keyof ProtocolSettings; setSettings({ ...settings, [key]: cloneDefaults()[key] }); } }}>Reset</Button><Button size="sm" variant="outline" leftIcon={<CodeBracketIcon width="15px" />} onClick={openConfig}>Generated config</Button><Button size="sm" colorScheme="primary" isLoading={save.isLoading} onClick={() => save.mutate()}>Apply</Button></HStack></HStack>
                <FormControl maxW="180px"><FormLabel fontSize="xs">Ingress port</FormLabel><NumberInput size="sm" min={1} max={65535} value={ports[selectedProtocol]} onChange={(_, next) => setPorts({ ...ports, [selectedProtocol]: next })}><NumberInputField aria-label="Ingress port" fontFamily="mono" /></NumberInput></FormControl>
                <Box borderTop="1px solid" borderColor="gray.200" pt={5}>
                  {selectedProtocol === "hysteria2" && <Hysteria2Editor value={settings.hysteria2} onChange={(value) => setSettings({ ...settings, hysteria2: value })} />}
                  {selectedProtocol === "tuic" && <TUICEditor value={settings.tuic} onChange={(value) => setSettings({ ...settings, tuic: value })} />}
                  {selectedProtocol === "anytls" && <AnyTLSEditor value={settings.anytls} onChange={(value) => setSettings({ ...settings, anytls: value })} />}
                  {!(["hysteria2", "tuic", "anytls"] as string[]).includes(selectedProtocol) && <Text fontSize="sm" color="gray.500">This protocol currently uses the validated sing-box defaults.</Text>}
                </Box>
              </VStack>
            </Grid>
          </TabPanel>
          <TabPanel px={0}><VStack align="stretch" spacing={0}>{relatedLinks.map((link) => { const peerId = link.from_node_id === id ? link.to_node_id : link.from_node_id; const peer = nodes.data?.find((item) => item.id === peerId); return <HStack key={link.id} py={3} borderBottom="1px solid" borderColor="gray.200" justify="space-between"><Box><Text fontSize="sm" fontWeight="medium">{link.from_node_id === id ? `${node.name} -> ${peer?.name}` : `${peer?.name} -> ${node.name}`}</Text><Text fontSize="xs" color="gray.500">{link.protocol}:{link.to_node_id === id ? node.node_link_port : peer?.node_link_port} / {link.mtls_enabled ? "mTLS" : "CA"}</Text></Box><Badge colorScheme={link.enabled ? "green" : "gray"}>{link.enabled ? "Active" : "Disabled"}</Badge></HStack>; })}</VStack></TabPanel>
          <TabPanel px={0}><Grid templateColumns={{ base: "1fr", md: "180px 1fr" }} rowGap={3} fontSize="sm"><Text color="gray.500">sing-box</Text><Text>{node.version || "Unknown"}</Text><Text color="gray.500">Desired config</Text><Text fontFamily="mono" fontSize="xs">{node.last_config_hash || "-"}</Text><Text color="gray.500">Applied config</Text><Text fontFamily="mono" fontSize="xs">{node.applied_config_hash || "-"}</Text><Text color="gray.500">Agent</Text><Text>{node.sync_enabled ? "Pull sync enabled" : "Not enrolled"}</Text></Grid></TabPanel>
        </TabPanels>
      </Tabs>
      <Modal isOpen={configModal.isOpen} onClose={configModal.onClose} size="4xl" isCentered><ModalOverlay /><ModalContent><ModalHeader as="h2">Generated configuration</ModalHeader><ModalCloseButton /><ModalBody pb={6}><Textarea readOnly minH="65vh" fontFamily="mono" fontSize="xs" value={generated.data ? JSON.stringify(generated.data.config, null, 2) : "Loading..."} /></ModalBody></ModalContent></Modal>
    </VStack>
  );
};
