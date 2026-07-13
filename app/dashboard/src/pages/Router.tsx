import { createHashRouter } from "react-router-dom";
import { fetch } from "../service/http";
import { getAuthToken } from "../utils/authStorage";
import { AppShell } from "components/AppShell";
import { Login } from "./Login";
import { Nodes } from "./Nodes";
import { Network } from "./Network";
import { NodeDetails } from "./NodeDetails";
import { Overview } from "./Overview";
import { UserConnections } from "./UserConnections";
import { Users } from "./Users";
const fetchAdminLoader = () => {
    return fetch("/admin", {
        headers: {
            Authorization: `Bearer ${getAuthToken()}`,
        },
    });
};
export const router = createHashRouter([
    {
        path: "/",
        element: <AppShell />,
        errorElement: <Login />,
        loader: fetchAdminLoader,
        children: [
            { index: true, element: <Overview /> },
            { path: "users", element: <Users /> },
            { path: "users/:username", element: <UserConnections /> },
            { path: "nodes", element: <Nodes /> },
            { path: "network", element: <Network /> },
            { path: "nodes/:nodeId", element: <NodeDetails /> },
        ],
    },
    {
        path: "/login/",
        element: <Login />,
    },
]);
