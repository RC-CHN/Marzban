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
  node_link_port: number;
  deploy_method: "manual" | "local" | "ssh";
  status: "connected" | "connecting" | "error" | "disabled";
  last_config_hash?: string | null;
  applied_config_hash?: string | null;
};

type SingBoxLink = {
  id: number;
  from_node_id: number;
  to_node_id: number;
  protocol: string;
  enabled: boolean;
  mtls_enabled: boolean;
};

const QueryKey = "singbox-panel";
const Protocols = [
  "hysteria2",
  "tuic",
  "anytls",
  "vmess",
  "vless",
  "trojan",
  "shadowsocks",
];

const Icon = ({ as: Component }: { as: ElementType }) => (
  <Component width="16px" height="16px" strokeWidth={2} />
);

export const SingBoxPanel: FC = () => {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [nodeName, setNodeName] = useState("");
  const [nodeHost, setNodeHost] = useState("");
  const [policyUsername, setPolicyUsername] = useState("");
  const [policyExitNodeId, setPolicyExitNodeId] = useState("");
  const [policyProtocols, setPolicyProtocols] = useState(Protocols);

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

  const invalidate = () => {
    queryClient.invalidateQueries([QueryKey, "nodes"]);
    queryClient.invalidateQueries([QueryKey, "links"]);
  };

  const addNode = useMutation(
    () =>
      fetch("/singbox/nodes", {
        method: "POST",
        body: {
          name: nodeName,
          public_host: nodeHost,
          rebuild_links: true,
        },
      }),
    {
      onSuccess: () => {
        setNodeName("");
        setNodeHost("");
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
      fetch(`/singbox/users/${policyUsername}/policy`, {
        method: "PUT",
        body: {
          exit_node_id: policyExitNodeId ? Number(policyExitNodeId) : null,
          enabled_protocols: policyProtocols,
        },
      }),
    {
      onSuccess: () => {
        generateSuccessMessage("sing-box user policy saved", toast);
      },
      onError: (e) => {
        generateErrorMessage(e, toast);
      },
    }
  );

  const nodes = nodesQuery.data || [];
  const links = linksQuery.data || [];

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
                    <Th>Entry</Th>
                    <Th>Exit</Th>
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
                        <Badge colorScheme={node.status === "connected" ? "green" : "gray"}>
                          {node.status}
                        </Badge>
                      </Td>
                      <Td>
                        <Tooltip label={node.applied_config_hash || node.last_config_hash || ""}>
                          <Text maxW="120px" isTruncated fontFamily="mono" fontSize="xs">
                            {node.applied_config_hash || node.last_config_hash || "-"}
                          </Text>
                        </Tooltip>
                      </Td>
                      <Td isNumeric>
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
              <HStack align="flex-end">
                <FormControl>
                  <FormLabel fontSize="xs">Name</FormLabel>
                  <Input size="sm" value={nodeName} onChange={(e) => setNodeName(e.target.value)} />
                </FormControl>
                <FormControl>
                  <FormLabel fontSize="xs">Address</FormLabel>
                  <Input size="sm" value={nodeHost} onChange={(e) => setNodeHost(e.target.value)} />
                </FormControl>
                <Button
                  size="sm"
                  onClick={() => addNode.mutate()}
                  isDisabled={!nodeName || !nodeHost}
                  isLoading={addNode.isLoading}
                  leftIcon={<Icon as={PlusIcon} />}
                >
                  Add
                </Button>
              </HStack>

              <Divider />

              <Text fontSize="sm" fontWeight="medium">
                User exit
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
            </VStack>
          </GridItem>
        </Grid>
      </VStack>
    </Box>
  );
};
