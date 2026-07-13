import {
  Badge,
  Box,
  Button,
  HStack,
  Skeleton,
  Tab,
  TabList,
  TabPanel,
  TabPanels,
  Tabs,
  Text,
  Tooltip,
  VStack,
  useToast,
} from "@chakra-ui/react";
import { ArrowLeftIcon, CheckIcon, ClipboardIcon } from "@heroicons/react/24/outline";
import { PageHeader } from "components/AppShell";
import { ConnectionEditor } from "components/ConnectionEditor";
import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "react-query";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams } from "react-router-dom";
import { fetch } from "service/http";
import { ConnectionDraft, NetworkWorkspace, UserWorkspace } from "types/SingBox";
import { generateErrorMessage, generateSuccessMessage } from "utils/toastHandler";

const toDraft = (workspace?: UserWorkspace): ConnectionDraft[] =>
  (workspace?.connections || []).map((connection) => ({
    id: connection.id,
    clientId: `connection-${connection.id}`,
    label: connection.label,
    protocol: connection.protocol,
    entry_node_id: connection.entry_node_id,
    exit_node_id: connection.exit_node_id,
    ingress_service_id: connection.ingress_service_id,
    egress_service_id: connection.egress_service_id,
    routing_policy_id: connection.routing_policy_id,
    enabled: connection.enabled,
    sort_order: connection.sort_order,
  }));

export const UserConnections = () => {
  const { t } = useTranslation();
  const { username = "" } = useParams();
  const decodedUsername = decodeURIComponent(username);
  const [draft, setDraft] = useState<ConnectionDraft[]>([]);
  const [selectedConnectionId, setSelectedConnectionId] = useState<string>();
  const navigate = useNavigate();
  const toast = useToast();
  const queryClient = useQueryClient();
  const workspace = useQuery(["singbox", "user", decodedUsername], () => fetch<UserWorkspace>(`/singbox/users/${encodeURIComponent(decodedUsername)}/connections`));
  const network = useQuery(["singbox", "network"], () => fetch<NetworkWorkspace>("/singbox/network"));
  useEffect(() => {
    if (!workspace.data) return;
    const nextDraft = toDraft(workspace.data);
    setDraft(nextDraft);
    setSelectedConnectionId((current) => current && nextDraft.some((item) => item.clientId === current) ? current : nextDraft[0]?.clientId);
  }, [workspace.data]);
  useEffect(() => {
    if (selectedConnectionId && draft.some((item) => item.clientId === selectedConnectionId)) return;
    setSelectedConnectionId(draft[0]?.clientId);
  }, [draft, selectedConnectionId]);
  const baseline = useMemo(() => JSON.stringify(toDraft(workspace.data)), [workspace.data]);
  const dirty = JSON.stringify(draft) !== baseline;
  const save = useMutation(
    () => fetch<UserWorkspace>(`/singbox/users/${encodeURIComponent(decodedUsername)}/connections`, {
      method: "PUT",
      body: { connections: draft.map(({ clientId, ...connection }) => connection) },
    }),
    {
      onSuccess: (data) => {
        queryClient.setQueryData(["singbox", "user", decodedUsername], data);
        queryClient.invalidateQueries(["singbox", "users"]);
        generateSuccessMessage(t("connections.applied"), toast);
      },
      onError: (error) => { generateErrorMessage(error, toast); },
    }
  );
  const absoluteUrl = (path: string) => path.startsWith("http") ? path : `${window.location.origin}${path}`;
  const copy = async (label: string, path: string) => {
    await navigator.clipboard.writeText(absoluteUrl(path));
    generateSuccessMessage(t("connections.subscriptionCopied", { format: label }), toast);
  };

  if (workspace.isLoading || network.isLoading) return <VStack align="stretch"><PageHeader title={t("usersControl.user")} /><Skeleton h="500px" /></VStack>;
  if (!workspace.data || !network.data) return <Text py={8}>{t("connections.userNotFound")}</Text>;
  const subscriptions = workspace.data.public_subscription;

  return (
    <VStack align="stretch" spacing={5}>
      <PageHeader
        title={workspace.data.username}
        actions={
          <HStack>
            <Badge colorScheme={workspace.data.status === "active" ? "green" : "gray"}>{t(`network.state.${workspace.data.status}`, { defaultValue: workspace.data.status })}</Badge>
            <Button size="sm" variant="outline" isDisabled={!dirty} onClick={() => setDraft(toDraft(workspace.data))}>{t("network.action.discard")}</Button>
            <Button size="sm" colorScheme="primary" leftIcon={<CheckIcon width="16px" />} isDisabled={!dirty} isLoading={save.isLoading} onClick={() => save.mutate()}>{t("connections.applyChanges")}</Button>
          </HStack>
        }
      />
      <HStack><Button size="xs" variant="ghost" leftIcon={<ArrowLeftIcon width="14px" />} onClick={() => navigate("/users")}>{t("shell.users")}</Button>{dirty && <Badge colorScheme="orange">{t("connections.draftChanges")}</Badge>}</HStack>

      <Box borderY="1px solid" borderColor="gray.200" _dark={{ borderColor: "gray.700" }} py={3}>
        <HStack justify="space-between" flexWrap="wrap" gap={3}>
          <Box><Text fontSize="sm" fontWeight="semibold">{t("connections.subscriptions")}</Text><Text fontSize="xs" color="gray.500">{t("connections.publishedCount", { count: draft.filter((connection) => connection.enabled).length })}</Text></Box>
          <HStack>
            {(["singbox", "clash", "v2rayn"] as const).map((format) => (
              <Button key={format} size="sm" variant="outline" leftIcon={<ClipboardIcon width="14px" />} onClick={() => copy(format, subscriptions[format])}>{format}</Button>
            ))}
          </HStack>
        </HStack>
      </Box>

      <Tabs variant="line" colorScheme="primary" isLazy>
        <TabList><Tab fontSize="sm">{t("connections.connections")}</Tab><Tab fontSize="sm">{t("network.tab.topology")}</Tab></TabList>
        <TabPanels>
          <TabPanel px={0}><ConnectionEditor mode="table" connections={draft} onChange={setDraft} network={network.data} selectedConnectionId={selectedConnectionId} onSelectConnection={setSelectedConnectionId} /></TabPanel>
          <TabPanel px={0}><ConnectionEditor mode="graph" connections={draft} onChange={setDraft} network={network.data} selectedConnectionId={selectedConnectionId} onSelectConnection={setSelectedConnectionId} /></TabPanel>
        </TabPanels>
      </Tabs>
    </VStack>
  );
};
