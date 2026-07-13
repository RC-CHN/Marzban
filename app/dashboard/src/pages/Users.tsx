import {
  Badge,
  Box,
  Button,
  FormControl,
  FormLabel,
  HStack,
  Input,
  InputGroup,
  InputLeftElement,
  Modal,
  ModalBody,
  ModalCloseButton,
  ModalContent,
  ModalFooter,
  ModalHeader,
  ModalOverlay,
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
  useDisclosure,
  useToast,
} from "@chakra-ui/react";
import { MagnifyingGlassIcon, PlusIcon } from "@heroicons/react/24/outline";
import { PageHeader } from "components/AppShell";
import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "react-query";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { fetch } from "service/http";
import { UserSummary } from "types/SingBox";
import { formatBytes } from "utils/formatByte";
import { generateErrorMessage } from "utils/toastHandler";

export const Users = () => {
  const { t } = useTranslation();
  const [search, setSearch] = useState("");
  const [username, setUsername] = useState("");
  const modal = useDisclosure();
  const navigate = useNavigate();
  const toast = useToast();
  const queryClient = useQueryClient();
  const users = useQuery(["singbox", "users"], () => fetch<UserSummary[]>("/singbox/users"));
  const createUser = useMutation(
    () => fetch("/singbox/users", { method: "POST", body: { username, data_limit: 0, expire: 0, initialize_connections: false } }),
    {
      onSuccess: () => {
        queryClient.invalidateQueries(["singbox", "users"]);
        modal.onClose();
        navigate(`/users/${encodeURIComponent(username)}`);
      },
      onError: (error) => { generateErrorMessage(error, toast); },
    }
  );
  const filtered = useMemo(
    () => (users.data || []).filter((user) => user.username.toLowerCase().includes(search.toLowerCase())),
    [search, users.data]
  );

  return (
    <VStack align="stretch" spacing={5}>
      <PageHeader
        title={t("shell.users")}
        actions={<Button size="sm" colorScheme="primary" leftIcon={<PlusIcon width="16px" />} onClick={modal.onOpen}>{t("usersControl.newUser")}</Button>}
      />
      <HStack justify="space-between">
        <InputGroup maxW="360px" size="sm">
          <InputLeftElement><MagnifyingGlassIcon width="16px" /></InputLeftElement>
          <Input placeholder={t("usersControl.search")} value={search} onChange={(event) => setSearch(event.target.value)} />
        </InputGroup>
        <Text fontSize="sm" color="gray.500">{t("usersControl.count", { count: filtered.length })}</Text>
      </HStack>
      {users.isLoading ? <Skeleton h="300px" /> : (
        <TableContainer bg="white" _dark={{ bg: "gray.800" }}>
          <Table size="sm">
            <Thead><Tr><Th>{t("usersControl.user")}</Th><Th>{t("network.column.status")}</Th><Th>{t("usersControl.connections")}</Th><Th>{t("usersControl.traffic")}</Th><Th>{t("usersControl.limit")}</Th><Th /></Tr></Thead>
            <Tbody>
              {filtered.map((user) => (
                <Tr key={user.username} className="interactive" onClick={() => navigate(`/users/${encodeURIComponent(user.username)}`)}>
                  <Td fontWeight="medium">{user.username}</Td>
                  <Td><Badge colorScheme={user.status === "active" ? "green" : "gray"}>{t(`network.state.${user.status}`, { defaultValue: user.status })}</Badge></Td>
                  <Td>{user.connection_count}</Td>
                  <Td>{formatBytes(user.used_traffic)}</Td>
                  <Td>{user.data_limit ? formatBytes(user.data_limit) : t("usersControl.unlimited")}</Td>
                  <Td isNumeric><Button size="xs" variant="ghost">{t("usersControl.manage")}</Button></Td>
                </Tr>
              ))}
            </Tbody>
          </Table>
        </TableContainer>
      )}

      <Modal isOpen={modal.isOpen} onClose={modal.onClose} isCentered>
        <ModalOverlay />
        <ModalContent>
          <ModalHeader>{t("usersControl.newUser")}</ModalHeader><ModalCloseButton />
          <ModalBody><FormControl><FormLabel>{t("usersControl.username")}</FormLabel><Input autoFocus value={username} onChange={(event) => setUsername(event.target.value)} /></FormControl></ModalBody>
          <ModalFooter><Button variant="ghost" mr={2} onClick={modal.onClose}>{t("network.action.cancel")}</Button><Button colorScheme="primary" isDisabled={username.length < 3} isLoading={createUser.isLoading} onClick={() => createUser.mutate()}>{t("usersControl.create")}</Button></ModalFooter>
        </ModalContent>
      </Modal>
    </VStack>
  );
};
