import {
  Badge,
  Box,
  Button,
  FormControl,
  FormLabel,
  HStack,
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
  SimpleGrid,
  Skeleton,
  Switch,
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
  useDisclosure,
  useToast,
} from "@chakra-ui/react";
import { ClipboardIcon, Cog6ToothIcon, PlusIcon, TrashIcon } from "@heroicons/react/24/outline";
import { PageHeader } from "components/AppShell";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "react-query";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { fetch } from "service/http";
import { DEFAULT_PUBLIC_PORTS, SINGBOX_PROTOCOLS, SingBoxNode, SingBoxProtocol } from "types/SingBox";
import { generateErrorMessage, generateSuccessMessage } from "utils/toastHandler";

type Enrollment = { command: string };

export const Nodes = () => {
  const { t } = useTranslation();
  const [name, setName] = useState("");
  const [host, setHost] = useState("");
  const [newPorts, setNewPorts] = useState({ ...DEFAULT_PUBLIC_PORTS });
  const [deletingNode, setDeletingNode] = useState<SingBoxNode | null>(null);
  const modal = useDisclosure();
  const deleteModal = useDisclosure();
  const navigate = useNavigate();
  const toast = useToast();
  const queryClient = useQueryClient();
  const nodes = useQuery(["singbox", "nodes"], () => fetch<SingBoxNode[]>("/singbox/nodes"), { refetchInterval: 30000 });
  const refresh = () => queryClient.invalidateQueries(["singbox", "nodes"]);
  const addNode = useMutation(
    () => fetch("/singbox/nodes", { method: "POST", body: { name, public_host: host, public_ports: newPorts, node_link_port: 12443, public_tls_mode: "system-ca", rebuild_links: true } }),
    { onSuccess: () => { refresh(); modal.onClose(); setName(""); setHost(""); setNewPorts({ ...DEFAULT_PUBLIC_PORTS }); }, onError: (error) => { generateErrorMessage(error, toast); } }
  );
  const updateNode = useMutation(
    ({ id, patch }: { id: number; patch: Partial<SingBoxNode> }) => fetch(`/singbox/nodes/${id}`, { method: "PUT", body: patch }),
    { onSuccess: refresh, onError: (error) => { generateErrorMessage(error, toast); } }
  );
  const enroll = useMutation(
    (node: SingBoxNode) => fetch<Enrollment>(`/singbox/nodes/${node.id}/enrollment`, { method: "POST", body: { expires_in_seconds: 1800 } }),
    {
      onSuccess: async (data) => {
        await navigator.clipboard.writeText(data.command);
        generateSuccessMessage(t("nodesControl.bootstrapCopied"), toast);
      },
      onError: (error) => { generateErrorMessage(error, toast); },
    }
  );
  const deleteNode = useMutation(
    (node: SingBoxNode) => fetch(`/singbox/nodes/${node.id}`, { method: "DELETE" }),
    {
      onSuccess: () => {
        refresh();
        deleteModal.onClose();
        setDeletingNode(null);
        generateSuccessMessage(t("nodesControl.nodeDeleted"), toast);
      },
      onError: (error) => { generateErrorMessage(error, toast); },
    }
  );
  const validPorts = (ports: Record<SingBoxProtocol, number>) => {
    const values = SINGBOX_PROTOCOLS.map((protocol) => ports[protocol]);
    return values.every((port) => Number.isInteger(port) && port > 0 && port <= 65535) && new Set(values).size === values.length;
  };
  const PortFields = ({ value, onChange }: { value: Record<SingBoxProtocol, number>; onChange: (ports: Record<SingBoxProtocol, number>) => void }) => (
    <SimpleGrid columns={{ base: 2, md: 3 }} spacing={3}>
      {SINGBOX_PROTOCOLS.map((protocol) => (
        <FormControl key={protocol}>
          <FormLabel fontSize="xs">{protocol}</FormLabel>
          <NumberInput size="sm" min={1} max={65535} value={value[protocol]} onChange={(_, port) => onChange({ ...value, [protocol]: port })}>
            <NumberInputField fontFamily="mono" />
          </NumberInput>
        </FormControl>
      ))}
    </SimpleGrid>
  );

  return (
    <VStack align="stretch" spacing={5}>
      <PageHeader title={t("shell.nodes")} actions={<Button size="sm" colorScheme="primary" leftIcon={<PlusIcon width="16px" />} onClick={modal.onOpen}>{t("nodesControl.addNode")}</Button>} />
      <HStack justify="space-between"><Text fontSize="sm" color="gray.500">{t("nodesControl.subtitle")}</Text><Text fontSize="sm" color="gray.500">{t("nodesControl.count", { count: nodes.data?.length || 0 })}</Text></HStack>
      {nodes.isLoading ? <Skeleton h="300px" /> : (
        <TableContainer bg="white" _dark={{ bg: "gray.800" }}>
          <Table size="sm">
            <Thead><Tr><Th>{t("nodesControl.node")}</Th><Th>{t("network.column.status")}</Th><Th>{t("nodesControl.entry")}</Th><Th>{t("nodesControl.exit")}</Th><Th>TLS</Th><Th>{t("nodesControl.version")}</Th><Th>{t("nodesControl.config")}</Th><Th>{t("nodesControl.nodePorts")}</Th><Th /></Tr></Thead>
            <Tbody>
              {(nodes.data || []).map((node) => {
                const pending = Boolean(node.last_config_hash && node.last_config_hash !== node.applied_config_hash);
                return (
                  <Tr key={node.id}>
                    <Td><Button variant="link" color="inherit" fontWeight="medium" onClick={() => navigate(`/nodes/${node.id}`)}>{node.name}</Button><Text fontSize="xs" color="gray.500">{node.public_host}</Text></Td>
                    <Td><Badge colorScheme={node.status === "connected" ? "green" : node.status === "error" ? "red" : "gray"}>{t(`network.state.${node.status}`, { defaultValue: node.status })}</Badge></Td>
                    <Td><Switch size="sm" isChecked={node.entry_enabled} onChange={(event) => updateNode.mutate({ id: node.id, patch: { entry_enabled: event.target.checked } })} /></Td>
                    <Td><Switch size="sm" isChecked={node.exit_enabled} onChange={(event) => updateNode.mutate({ id: node.id, patch: { exit_enabled: event.target.checked } })} /></Td>
                    <Td><Badge colorScheme={node.public_tls_mode === "ip-insecure" ? "orange" : "green"}>{node.public_tls_mode}</Badge></Td>
                    <Td fontSize="xs">{node.version || "-"}</Td>
                    <Td><Badge colorScheme={pending ? "orange" : "green"}>{t(pending ? "overview.pending" : "overview.synced")}</Badge></Td>
                    <Td><Button size="xs" variant="ghost" leftIcon={<Cog6ToothIcon width="14px" />} onClick={() => navigate(`/nodes/${node.id}?protocol=hysteria2`)}>{t("nodesControl.configure")}</Button></Td>
                    <Td isNumeric><HStack justify="end"><Tooltip label={t("nodesControl.copyBootstrap")}><Button size="xs" variant="outline" leftIcon={<ClipboardIcon width="14px" />} isLoading={enroll.isLoading} onClick={() => enroll.mutate(node)}>{t("nodesControl.enroll")}</Button></Tooltip><Tooltip label={t("nodesControl.deleteNode")}><Button aria-label={t("nodesControl.deleteNamed", { name: node.name })} size="xs" variant="ghost" colorScheme="red" onClick={() => { setDeletingNode(node); deleteModal.onOpen(); }}><TrashIcon width="15px" /></Button></Tooltip></HStack></Td>
                  </Tr>
                );
              })}
            </Tbody>
          </Table>
        </TableContainer>
      )}

      <Modal isOpen={modal.isOpen} onClose={modal.onClose} isCentered>
        <ModalOverlay /><ModalContent><ModalHeader>{t("nodesControl.addNode")}</ModalHeader><ModalCloseButton />
          <ModalBody><VStack align="stretch" spacing={4}><FormControl><FormLabel>{t("network.field.name")}</FormLabel><Input value={name} onChange={(event) => setName(event.target.value)} /></FormControl><FormControl><FormLabel>{t("nodesControl.publicAddress")}</FormLabel><Input placeholder={t("nodesControl.ipOrDns")} value={host} onChange={(event) => setHost(event.target.value)} /></FormControl><Box><Text fontSize="sm" fontWeight="medium" mb={2}>{t("nodesControl.ingressPorts")}</Text><PortFields value={newPorts} onChange={setNewPorts} /></Box><Text fontSize="xs" color="gray.500">{t("nodesControl.linkPortHelp")}</Text></VStack></ModalBody>
          <ModalFooter><Button variant="ghost" mr={2} onClick={modal.onClose}>{t("network.action.cancel")}</Button><Button colorScheme="primary" isDisabled={!name || !host || !validPorts(newPorts)} isLoading={addNode.isLoading} onClick={() => addNode.mutate()}>{t("nodesControl.addNode")}</Button></ModalFooter>
        </ModalContent>
      </Modal>

      <Modal isOpen={deleteModal.isOpen} onClose={deleteModal.onClose} isCentered>
        <ModalOverlay /><ModalContent><ModalHeader as="h2">{t("nodesControl.deleteTitle", { name: deletingNode?.name })}</ModalHeader><ModalCloseButton />
          <ModalBody><VStack align="stretch" spacing={3}><Text>{t("nodesControl.deleteBlockedHelp")}</Text><Text fontSize="sm" color="gray.500">{t("nodesControl.deleteRuntimeHelp")}</Text></VStack></ModalBody>
          <ModalFooter><Button variant="ghost" mr={2} onClick={deleteModal.onClose}>{t("network.action.cancel")}</Button><Button colorScheme="red" isLoading={deleteNode.isLoading} onClick={() => deletingNode && deleteNode.mutate(deletingNode)}>{t("nodesControl.deleteNode")}</Button></ModalFooter>
        </ModalContent>
      </Modal>
    </VStack>
  );
};
