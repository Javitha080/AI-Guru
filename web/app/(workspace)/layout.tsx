import WorkspaceSidebar from "@/components/sidebar/WorkspaceSidebar";
import AppShell from "@/components/layout/AppShell";
import { CapabilityAccessProvider } from "@/components/access/CapabilityAccessContext";
import CapabilityGate from "@/components/access/CapabilityGate";
import { UnifiedChatProvider } from "@/context/UnifiedChatContext";
import FloatingGuru from "@/components/floating/FloatingGuru";
import FirstRunGate from "@/components/onboarding/FirstRunGate";

export default function WorkspaceLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <CapabilityAccessProvider>
      <UnifiedChatProvider>
        <AppShell sidebar={<WorkspaceSidebar />}>
          <CapabilityGate>{children}</CapabilityGate>
          <FloatingGuru />
          <FirstRunGate />
        </AppShell>
      </UnifiedChatProvider>
    </CapabilityAccessProvider>
  );
}
