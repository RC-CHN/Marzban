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
import { useNavigate } from "react-router-dom";
import { fetch } from "service/http";
import { UserSummary } from "types/SingBox";
import { formatBytes } from "utils/formatByte";
import { generateErrorMessage } from "utils/toastHandler";

export const Users = () => {
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
        title="Users"
        actions={<Button size="sm" colorScheme="primary" leftIcon={<PlusIcon width="16px" />} onClick={modal.onOpen}>New user</Button>}
      />
      <HStack justify="space-between">
        <InputGroup maxW="360px" size="sm">
          <InputLeftElement><MagnifyingGlassIcon width="16px" /></InputLeftElement>
          <Input placeholder="Search users" value={search} onChange={(event) => setSearch(event.target.value)} />
        </InputGroup>
        <Text fontSize="sm" color="gray.500">{filtered.length} users</Text>
      </HStack>
      {users.isLoading ? <Skeleton h="300px" /> : (
        <TableContainer bg="white" _dark={{ bg: "gray.800" }}>
          <Table size="sm">
            <Thead><Tr><Th>User</Th><Th>Status</Th><Th>Connections</Th><Th>Traffic</Th><Th>Limit</Th><Th /></Tr></Thead>
            <Tbody>
              {filtered.map((user) => (
                <Tr key={user.username} className="interactive" onClick={() => navigate(`/users/${encodeURIComponent(user.username)}`)}>
                  <Td fontWeight="medium">{user.username}</Td>
                  <Td><Badge colorScheme={user.status === "active" ? "green" : "gray"}>{user.status}</Badge></Td>
                  <Td>{user.connection_count}</Td>
                  <Td>{formatBytes(user.used_traffic)}</Td>
                  <Td>{user.data_limit ? formatBytes(user.data_limit) : "Unlimited"}</Td>
                  <Td isNumeric><Button size="xs" variant="ghost">Manage</Button></Td>
                </Tr>
              ))}
            </Tbody>
          </Table>
        </TableContainer>
      )}

      <Modal isOpen={modal.isOpen} onClose={modal.onClose} isCentered>
        <ModalOverlay />
        <ModalContent>
          <ModalHeader>New user</ModalHeader><ModalCloseButton />
          <ModalBody><FormControl><FormLabel>Username</FormLabel><Input autoFocus value={username} onChange={(event) => setUsername(event.target.value)} /></FormControl></ModalBody>
          <ModalFooter><Button variant="ghost" mr={2} onClick={modal.onClose}>Cancel</Button><Button colorScheme="primary" isDisabled={username.length < 3} isLoading={createUser.isLoading} onClick={() => createUser.mutate()}>Create</Button></ModalFooter>
        </ModalContent>
      </Modal>
    </VStack>
  );
};
