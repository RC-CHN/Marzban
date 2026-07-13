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
import { useTranslation } from "react-i18next";
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

export const Hysteria2Editor = ({ value, onChange }: { value: Hysteria2Settings; onChange: (value: Hysteria2Settings) => void }) => {
  const { t } = useTranslation();
  return <VStack align="stretch" spacing={5}>
      <Grid templateColumns={{ base: "1fr", md: "1fr 1fr" }} gap={4}>
        <NumberField label={t("network.protocol.uploadLimit")} value={value.up_mbps} onChange={(next) => onChange({ ...value, up_mbps: next })} />
        <NumberField label={t("network.protocol.downloadLimit")} value={value.down_mbps} onChange={(next) => onChange({ ...value, down_mbps: next })} />
      </Grid>
      <FormControl display="flex" alignItems="center" justifyContent="space-between"><FormLabel fontSize="sm" mb={0}>{t("network.protocol.ignoreClientBandwidth")}</FormLabel><Switch isChecked={value.ignore_client_bandwidth} onChange={(event) => onChange({ ...value, ignore_client_bandwidth: event.target.checked })} /></FormControl>
      <Grid templateColumns={{ base: "1fr", md: "180px 1fr" }} gap={4}>
        <FormControl><FormLabel fontSize="xs">{t("network.protocol.obfuscation")}</FormLabel><Select size="sm" value={value.obfs_type} onChange={(event) => onChange({ ...value, obfs_type: event.target.value as Hysteria2Settings["obfs_type"] })}><option value="none">{t("network.protocol.obfuscationDisabled")}</option><option value="salamander">Salamander</option></Select></FormControl>
        <FormControl isDisabled={value.obfs_type === "none"}><FormLabel fontSize="xs">{t("network.protocol.obfsPassword")}</FormLabel><Input size="sm" type="password" value={value.obfs_password || ""} onChange={(event) => onChange({ ...value, obfs_password: event.target.value || null })} /></FormControl>
      </Grid>
      <FormControl><FormLabel fontSize="xs">{t("network.protocol.masqueradeUrl")}</FormLabel><Input size="sm" placeholder="https://origin.example" value={value.masquerade_url || ""} onChange={(event) => onChange({ ...value, masquerade_url: event.target.value || null })} /></FormControl>
    </VStack>;
};

export const TUICEditor = ({ value, onChange }: { value: TUICSettings; onChange: (value: TUICSettings) => void }) => {
  const { t } = useTranslation();
  return <VStack align="stretch" spacing={5}>
      <Grid templateColumns={{ base: "1fr", md: "repeat(3, 1fr)" }} gap={4}>
        <FormControl><FormLabel fontSize="xs">{t("network.protocol.congestionControl")}</FormLabel><Select size="sm" value={value.congestion_control} onChange={(event) => onChange({ ...value, congestion_control: event.target.value as TUICSettings["congestion_control"] })}><option value="bbr">BBR</option><option value="cubic">Cubic</option><option value="new_reno">New Reno</option></Select></FormControl>
        <FormControl><FormLabel fontSize="xs">{t("network.protocol.authTimeout")}</FormLabel><Input size="sm" fontFamily="mono" value={value.auth_timeout} onChange={(event) => onChange({ ...value, auth_timeout: event.target.value })} /></FormControl>
        <FormControl><FormLabel fontSize="xs">{t("network.protocol.heartbeat")}</FormLabel><Input size="sm" fontFamily="mono" value={value.heartbeat} onChange={(event) => onChange({ ...value, heartbeat: event.target.value })} /></FormControl>
      </Grid>
      <FormControl display="flex" alignItems="center" justifyContent="space-between"><Box><FormLabel fontSize="sm" mb={0}>{t("network.protocol.zeroRtt")}</FormLabel><Text fontSize="xs" color="orange.500">{t("network.protocol.replayWarning")}</Text></Box><Switch colorScheme="orange" isChecked={value.zero_rtt_handshake} onChange={(event) => onChange({ ...value, zero_rtt_handshake: event.target.checked })} /></FormControl>
    </VStack>;
};

export const AnyTLSEditor = ({ value, onChange }: { value: AnyTLSSettings; onChange: (value: AnyTLSSettings) => void }) => {
  const { t } = useTranslation();
  return <VStack align="stretch" spacing={5}>
      <Grid templateColumns={{ base: "1fr", md: "repeat(3, 1fr)" }} gap={4}>
        <FormControl><FormLabel fontSize="xs">{t("network.protocol.idleCheckInterval")}</FormLabel><Input size="sm" fontFamily="mono" value={value.idle_session_check_interval} onChange={(event) => onChange({ ...value, idle_session_check_interval: event.target.value })} /></FormControl>
        <FormControl><FormLabel fontSize="xs">{t("network.protocol.idleTimeout")}</FormLabel><Input size="sm" fontFamily="mono" value={value.idle_session_timeout} onChange={(event) => onChange({ ...value, idle_session_timeout: event.target.value })} /></FormControl>
        <FormControl><FormLabel fontSize="xs">{t("network.protocol.minimumIdleSessions")}</FormLabel><NumberInput size="sm" min={0} max={1024} value={value.min_idle_session} onChange={(_, next) => onChange({ ...value, min_idle_session: next })}><NumberInputField fontFamily="mono" /></NumberInput></FormControl>
      </Grid>
      <FormControl><FormLabel fontSize="xs">{t("network.protocol.paddingScheme")}</FormLabel><Textarea minH="170px" fontFamily="mono" fontSize="xs" placeholder={t("network.protocol.paddingPlaceholder")} value={(value.padding_scheme || []).join("\n")} onChange={(event) => onChange({ ...value, padding_scheme: event.target.value.trim() ? event.target.value.split("\n") : null })} /></FormControl>
    </VStack>;
};

export const NodeDetails = () => {
  const { t } = useTranslation();
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
        generateSuccessMessage(t("nodeDetails.profileApplied"), toast);
      },
      onError: (error) => { generateErrorMessage(error, toast); },
    }
  );
  const relatedLinks = useMemo(() => (links.data || []).filter((link) => link.from_node_id === id || link.to_node_id === id), [id, links.data]);
  const openConfig = async () => { await generated.refetch(); configModal.onOpen(); };
  if (nodes.isLoading) return <Skeleton h="500px" />;
  if (!node) return <Text py={8}>{t("nodeDetails.notFound")}</Text>;
  const pending = Boolean(node.last_config_hash && node.last_config_hash !== node.applied_config_hash);
  const selectedIsDefault = profileIsDefault(selectedProtocol, settings);

  return (
    <VStack align="stretch" spacing={5}>
      <PageHeader title={node.name} actions={<HStack><Badge colorScheme={node.status === "connected" ? "green" : "gray"}>{t(`network.state.${node.status}`, { defaultValue: node.status })}</Badge><Badge colorScheme={pending ? "orange" : "green"}>{t(pending ? "overview.pending" : "nodeDetails.applied")}</Badge></HStack>} />
      <Button alignSelf="start" size="xs" variant="ghost" leftIcon={<ArrowLeftIcon width="14px" />} onClick={() => navigate("/nodes")}>{t("shell.nodes")}</Button>
      <Tabs variant="line" colorScheme="primary" isLazy defaultIndex={requestedProtocol ? 1 : 0}>
        <TabList><Tab>{t("shell.overview")}</Tab><Tab>{t("connections.ingress")}</Tab><Tab>{t("nodeDetails.links")}</Tab><Tab>{t("overview.runtime")}</Tab></TabList>
        <TabPanels>
          <TabPanel px={0}><Grid templateColumns={{ base: "1fr", md: "180px 1fr" }} rowGap={3} fontSize="sm"><Text color="gray.500">{t("nodesControl.publicAddress")}</Text><Text fontFamily="mono">{node.public_host}</Text><Text color="gray.500">{t("nodeDetails.publicTls")}</Text><Text>{node.public_tls_mode}</Text><Text color="gray.500">{t("nodeDetails.linkPort")}</Text><Text fontFamily="mono">{node.node_link_port}</Text><Text color="gray.500">{t("overview.lastSeen")}</Text><Text>{node.last_seen_at || t("overview.never")}</Text></Grid></TabPanel>
          <TabPanel px={0}>
            <Grid templateColumns={{ base: "1fr", lg: "230px minmax(0, 1fr)" }} gap={6}>
              <VStack align="stretch" spacing={0} borderRight={{ lg: "1px solid" }} borderColor="gray.200" pr={{ lg: 4 }}>
                {SINGBOX_PROTOCOLS.map((protocol) => <Button key={protocol} h="48px" justifyContent="space-between" borderRadius="0" variant={selectedProtocol === protocol ? "solid" : "ghost"} colorScheme={selectedProtocol === protocol ? "primary" : "gray"} onClick={() => setSelectedProtocol(protocol)}><Text>{protocol}</Text><Text fontSize="xs" fontFamily="mono">:{ports[protocol]}</Text></Button>)}
              </VStack>
              <VStack align="stretch" spacing={5} minW={0}>
                <HStack justify="space-between" align="start" flexWrap="wrap"><Box><HStack><Text fontWeight="semibold">{node.name} / {selectedProtocol}</Text><Badge colorScheme={selectedIsDefault ? "gray" : "blue"}>{t(selectedIsDefault ? "nodeDetails.default" : "nodeDetails.override")}</Badge></HStack><Text fontSize="xs" color="gray.500">{t("nodeDetails.sharedBy", { count: impact.data?.protocols[selectedProtocol] || 0 })}</Text></Box><HStack><Button size="sm" variant="ghost" leftIcon={<ArrowPathIcon width="15px" />} onClick={() => { if (selectedProtocol in DEFAULT_PROTOCOL_SETTINGS) { const key = selectedProtocol as keyof ProtocolSettings; setSettings({ ...settings, [key]: cloneDefaults()[key] }); } }}>{t("nodeDetails.reset")}</Button><Button size="sm" variant="outline" leftIcon={<CodeBracketIcon width="15px" />} onClick={openConfig}>{t("nodeDetails.generatedConfig")}</Button><Button size="sm" colorScheme="primary" isLoading={save.isLoading} onClick={() => save.mutate()}>{t("apply")}</Button></HStack></HStack>
                <FormControl maxW="180px"><FormLabel fontSize="xs">{t("nodeDetails.ingressPort")}</FormLabel><NumberInput size="sm" min={1} max={65535} value={ports[selectedProtocol]} onChange={(_, next) => setPorts({ ...ports, [selectedProtocol]: next })}><NumberInputField aria-label={t("nodeDetails.ingressPort")} fontFamily="mono" /></NumberInput></FormControl>
                <Box borderTop="1px solid" borderColor="gray.200" pt={5}>
                  {selectedProtocol === "hysteria2" && <Hysteria2Editor value={settings.hysteria2} onChange={(value) => setSettings({ ...settings, hysteria2: value })} />}
                  {selectedProtocol === "tuic" && <TUICEditor value={settings.tuic} onChange={(value) => setSettings({ ...settings, tuic: value })} />}
                  {selectedProtocol === "anytls" && <AnyTLSEditor value={settings.anytls} onChange={(value) => setSettings({ ...settings, anytls: value })} />}
                  {!(["hysteria2", "tuic", "anytls"] as string[]).includes(selectedProtocol) && <Text fontSize="sm" color="gray.500">{t("network.message.defaultProfile")}</Text>}
                </Box>
              </VStack>
            </Grid>
          </TabPanel>
          <TabPanel px={0}><VStack align="stretch" spacing={0}>{relatedLinks.map((link) => { const peerId = link.from_node_id === id ? link.to_node_id : link.from_node_id; const peer = nodes.data?.find((item) => item.id === peerId); return <HStack key={link.id} py={3} borderBottom="1px solid" borderColor="gray.200" justify="space-between"><Box><Text fontSize="sm" fontWeight="medium">{link.from_node_id === id ? `${node.name} -> ${peer?.name}` : `${peer?.name} -> ${node.name}`}</Text><Text fontSize="xs" color="gray.500">{link.protocol}:{link.to_node_id === id ? node.node_link_port : peer?.node_link_port} / {link.mtls_enabled ? "mTLS" : "CA"}</Text></Box><Badge colorScheme={link.enabled ? "green" : "gray"}>{t(link.enabled ? "network.state.enabled" : "network.state.disabled")}</Badge></HStack>; })}</VStack></TabPanel>
          <TabPanel px={0}><Grid templateColumns={{ base: "1fr", md: "180px 1fr" }} rowGap={3} fontSize="sm"><Text color="gray.500">sing-box</Text><Text>{node.version || t("network.state.unknown")}</Text><Text color="gray.500">{t("nodeDetails.desiredConfig")}</Text><Text fontFamily="mono" fontSize="xs">{node.last_config_hash || "-"}</Text><Text color="gray.500">{t("nodeDetails.appliedConfig")}</Text><Text fontFamily="mono" fontSize="xs">{node.applied_config_hash || "-"}</Text><Text color="gray.500">{t("nodeDetails.agent")}</Text><Text>{t(node.sync_enabled ? "nodeDetails.pullSync" : "nodeDetails.notEnrolled")}</Text></Grid></TabPanel>
        </TabPanels>
      </Tabs>
      <Modal isOpen={configModal.isOpen} onClose={configModal.onClose} size="4xl" isCentered><ModalOverlay /><ModalContent><ModalHeader as="h2">{t("nodeDetails.generatedConfiguration")}</ModalHeader><ModalCloseButton /><ModalBody pb={6}><Textarea readOnly minH="65vh" fontFamily="mono" fontSize="xs" value={generated.data ? JSON.stringify(generated.data.config, null, 2) : t("nodeDetails.loading")} /></ModalBody></ModalContent></Modal>
    </VStack>
  );
};
