import {
  Box,
  Button,
  Divider,
  Drawer,
  DrawerBody,
  DrawerContent,
  DrawerOverlay,
  HStack,
  IconButton,
  Text,
  Tooltip,
  VStack,
  useColorMode,
  useDisclosure,
} from "@chakra-ui/react";
import {
  ArrowLeftOnRectangleIcon,
  Bars3Icon,
  MoonIcon,
  ServerStackIcon,
  ShareIcon,
  Squares2X2Icon,
  SunIcon,
  UsersIcon,
} from "@heroicons/react/24/outline";
import { Language } from "components/Language";
import { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { removeAuthToken } from "utils/authStorage";
import { updateThemeColor } from "utils/themeColor";

const navItems = [
  { to: "/", labelKey: "shell.overview", icon: Squares2X2Icon },
  { to: "/users", labelKey: "shell.users", icon: UsersIcon },
  { to: "/nodes", labelKey: "shell.nodes", icon: ServerStackIcon },
  { to: "/network", labelKey: "shell.network", icon: ShareIcon },
];

const Navigation = ({ onNavigate }: { onNavigate?: () => void }) => {
  const { t } = useTranslation();
  return <VStack align="stretch" spacing={1}>
      {navItems.map((item) => (
        <NavLink key={item.to} to={item.to} end={item.to === "/"} onClick={onNavigate}>
          {({ isActive }) => (
            <HStack
              h="40px"
              px={3}
              borderRadius="6px"
              color={isActive ? "gray.900" : "gray.600"}
              bg={isActive ? "gray.100" : "transparent"}
              _dark={{ color: isActive ? "white" : "gray.400", bg: isActive ? "gray.700" : "transparent" }}
              _hover={{ bg: isActive ? undefined : "gray.50", _dark: { bg: "gray.750" } }}
            >
              <item.icon width="18px" height="18px" />
              <Text fontSize="sm" fontWeight={isActive ? "semibold" : "medium"}>
                {t(item.labelKey)}
              </Text>
            </HStack>
          )}
        </NavLink>
      ))}
    </VStack>;
};

const Brand = () => {
  const { t } = useTranslation();
  return <HStack h="64px" px={4}>
      <Box w="9px" h="28px" bg="primary.500" borderRadius="2px" />
      <Box>
        <Text fontSize="md" fontWeight="700" lineHeight="short">
          Marzban
        </Text>
        <Text fontSize="xs" color="gray.500">
          {t("shell.brandSubtitle")}
        </Text>
      </Box>
    </HStack>;
};

export const PageHeader = ({ title, actions }: { title: string; actions?: ReactNode }) => (
  <HStack minH="56px" py={2} justify="space-between" flexWrap="wrap" borderBottom="1px solid" borderColor="gray.200" _dark={{ borderColor: "gray.700" }}>
    <Text as="h1" fontSize="lg" fontWeight="semibold">
      {title}
    </Text>
    {actions}
  </HStack>
);

export const AppShell = () => {
  const { t } = useTranslation();
  const drawer = useDisclosure();
  const { colorMode, toggleColorMode } = useColorMode();
  const navigate = useNavigate();
  const logout = () => {
    removeAuthToken();
    navigate("/login");
  };

  return (
    <Box minH="100vh" bg="gray.50" _dark={{ bg: "gray.900" }}>
      <Box
        display={{ base: "none", lg: "block" }}
        position="fixed"
        insetY={0}
        left={0}
        w="220px"
        bg="white"
        borderRight="1px solid"
        borderColor="gray.200"
        _dark={{ bg: "gray.800", borderColor: "gray.700" }}
      >
        <Brand />
        <Divider />
        <Box p={3}>
          <Navigation />
        </Box>
      </Box>

      <Box ml={{ base: 0, lg: "220px" }}>
        <HStack
          h="56px"
          px={{ base: 4, md: 6 }}
          justify="space-between"
          bg="white"
          borderBottom="1px solid"
          borderColor="gray.200"
          _dark={{ bg: "gray.800", borderColor: "gray.700" }}
        >
          <HStack>
            <IconButton
              display={{ base: "inline-flex", lg: "none" }}
              aria-label={t("shell.openNavigation")}
              icon={<Bars3Icon width="20px" />}
              variant="ghost"
              onClick={drawer.onOpen}
            />
            <Text fontSize="sm" color="gray.500">
              {t("shell.clusterControlPlane")}
            </Text>
          </HStack>
          <HStack>
            <Language />
            <Tooltip label={colorMode === "light" ? t("shell.darkMode") : t("shell.lightMode")}>
              <IconButton
                aria-label={t("shell.toggleColorMode")}
                variant="ghost"
                icon={colorMode === "light" ? <MoonIcon width="18px" /> : <SunIcon width="18px" />}
                onClick={() => {
                  updateThemeColor(colorMode === "light" ? "dark" : "light");
                  toggleColorMode();
                }}
              />
            </Tooltip>
            <Tooltip label={t("shell.signOut")}>
              <IconButton
                aria-label={t("shell.signOut")}
                variant="ghost"
                icon={<ArrowLeftOnRectangleIcon width="18px" />}
                onClick={logout}
              />
            </Tooltip>
          </HStack>
        </HStack>
        <Box as="main" px={{ base: 4, md: 6 }} pb={8} maxW="1600px" mx="auto">
          <Outlet />
        </Box>
      </Box>

      <Drawer isOpen={drawer.isOpen} placement="left" onClose={drawer.onClose}>
        <DrawerOverlay />
        <DrawerContent maxW="240px">
          <Brand />
          <Divider />
          <DrawerBody p={3}>
            <Navigation onNavigate={drawer.onClose} />
          </DrawerBody>
        </DrawerContent>
      </Drawer>
    </Box>
  );
};
