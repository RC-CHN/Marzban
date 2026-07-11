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
import { useNavigate } from "react-router-dom";
import { fetch } from "service/http";
import { DEFAULT_PUBLIC_PORTS, SINGBOX_PROTOCOLS, SingBoxNode, SingBoxProtocol } from "types/SingBox";
import { generateErrorMessage, generateSuccessMessage } from "utils/toastHandler";

type Enrollment = { command: string };

export const Nodes = () => {
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
        generateSuccessMessage("Bootstrap command copied", toast);
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
        generateSuccessMessage("Node deleted", toast);
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
      <PageHeader title="Nodes" actions={<Button size="sm" colorScheme="primary" leftIcon={<PlusIcon width="16px" />} onClick={modal.onOpen}>Add node</Button>} />
      <HStack justify="space-between"><Text fontSize="sm" color="gray.500">Public ingress and one-hop exits</Text><Text fontSize="sm" color="gray.500">{nodes.data?.length || 0} nodes</Text></HStack>
      {nodes.isLoading ? <Skeleton h="300px" /> : (
        <TableContainer bg="white" _dark={{ bg: "gray.800" }}>
          <Table size="sm">
            <Thead><Tr><Th>Node</Th><Th>Status</Th><Th>Entry</Th><Th>Exit</Th><Th>TLS</Th><Th>Version</Th><Th>Config</Th><Th>Node ports</Th><Th /></Tr></Thead>
            <Tbody>
              {(nodes.data || []).map((node) => {
                const pending = Boolean(node.last_config_hash && node.last_config_hash !== node.applied_config_hash);
                return (
                  <Tr key={node.id}>
                    <Td><Button variant="link" color="inherit" fontWeight="medium" onClick={() => navigate(`/nodes/${node.id}`)}>{node.name}</Button><Text fontSize="xs" color="gray.500">{node.public_host}</Text></Td>
                    <Td><Badge colorScheme={node.status === "connected" ? "green" : node.status === "error" ? "red" : "gray"}>{node.status}</Badge></Td>
                    <Td><Switch size="sm" isChecked={node.entry_enabled} onChange={(event) => updateNode.mutate({ id: node.id, patch: { entry_enabled: event.target.checked } })} /></Td>
                    <Td><Switch size="sm" isChecked={node.exit_enabled} onChange={(event) => updateNode.mutate({ id: node.id, patch: { exit_enabled: event.target.checked } })} /></Td>
                    <Td><Badge colorScheme={node.public_tls_mode === "ip-insecure" ? "orange" : "green"}>{node.public_tls_mode}</Badge></Td>
                    <Td fontSize="xs">{node.version || "-"}</Td>
                    <Td><Badge colorScheme={pending ? "orange" : "green"}>{pending ? "pending" : "synced"}</Badge></Td>
                    <Td><Button size="xs" variant="ghost" leftIcon={<Cog6ToothIcon width="14px" />} onClick={() => navigate(`/nodes/${node.id}?protocol=hysteria2`)}>Configure</Button></Td>
                    <Td isNumeric><HStack justify="end"><Tooltip label="Copy bootstrap command"><Button size="xs" variant="outline" leftIcon={<ClipboardIcon width="14px" />} isLoading={enroll.isLoading} onClick={() => enroll.mutate(node)}>Enroll</Button></Tooltip><Tooltip label="Delete node"><Button aria-label={`Delete ${node.name}`} size="xs" variant="ghost" colorScheme="red" onClick={() => { setDeletingNode(node); deleteModal.onOpen(); }}><TrashIcon width="15px" /></Button></Tooltip></HStack></Td>
                  </Tr>
                );
              })}
            </Tbody>
          </Table>
        </TableContainer>
      )}

      <Modal isOpen={modal.isOpen} onClose={modal.onClose} isCentered>
        <ModalOverlay /><ModalContent><ModalHeader>Add node</ModalHeader><ModalCloseButton />
          <ModalBody><VStack align="stretch" spacing={4}><FormControl><FormLabel>Name</FormLabel><Input value={name} onChange={(event) => setName(event.target.value)} /></FormControl><FormControl><FormLabel>Public address</FormLabel><Input placeholder="IP or DNS" value={host} onChange={(event) => setHost(event.target.value)} /></FormControl><Box><Text fontSize="sm" fontWeight="medium" mb={2}>Ingress protocol ports</Text><PortFields value={newPorts} onChange={setNewPorts} /></Box><Text fontSize="xs" color="gray.500">Node-link starts at 12443 and selects the next free port during enrollment.</Text></VStack></ModalBody>
          <ModalFooter><Button variant="ghost" mr={2} onClick={modal.onClose}>Cancel</Button><Button colorScheme="primary" isDisabled={!name || !host || !validPorts(newPorts)} isLoading={addNode.isLoading} onClick={() => addNode.mutate()}>Add node</Button></ModalFooter>
        </ModalContent>
      </Modal>

      <Modal isOpen={deleteModal.isOpen} onClose={deleteModal.onClose} isCentered>
        <ModalOverlay /><ModalContent><ModalHeader as="h2">Delete {deletingNode?.name}</ModalHeader><ModalCloseButton />
          <ModalBody><VStack align="stretch" spacing={3}><Text>Connections using this node must be moved or deleted first.</Text><Text fontSize="sm" color="gray.500">This removes the control-plane record. It does not stop or uninstall the node runtime.</Text></VStack></ModalBody>
          <ModalFooter><Button variant="ghost" mr={2} onClick={deleteModal.onClose}>Cancel</Button><Button colorScheme="red" isLoading={deleteNode.isLoading} onClick={() => deletingNode && deleteNode.mutate(deletingNode)}>Delete node</Button></ModalFooter>
        </ModalContent>
      </Modal>
    </VStack>
  );
};
