import { Box, VStack } from "@chakra-ui/react";
import { Footer } from "components/Footer";
import { Header } from "components/Header";
import { SingBoxPanel } from "components/SingBoxPanel";
import { FC } from "react";

export const Dashboard: FC = () => {
  return (
    <VStack justifyContent="space-between" minH="100vh" p="6" rowGap={4}>
      <Box w="full">
        <Header />
        <SingBoxPanel />
      </Box>
      <Footer />
    </VStack>
  );
};

export default Dashboard;
