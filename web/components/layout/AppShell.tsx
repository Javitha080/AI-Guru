"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";
import { usePathname } from "next/navigation";
import { Menu } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useDevice } from "@/hooks/useDevice";
import HeaderBar from "@/components/layout/HeaderBar";
import FloatingDock from "@/components/layout/FloatingDock";
import HistoryDrawer from "@/components/layout/HistoryDrawer";
import type { ReactNode } from "react";

/* Lets the sidebar dismiss the drawer after a nav click without every layout
   threading a callback down through WorkspaceSidebar/UtilitySidebar. Null on
   desktop and anywhere outside AppShell, so `drawer?.close()` is a no-op there
   rather than a crash. */
const SidebarDrawerContext = createContext<{ close: () => void } | null>(null);

export function useSidebarDrawer() {
  return useContext(SidebarDrawerContext);
}

interface AppShellProps {
  /** The route group's sidebar content (used for session history panel). */
  sidebar?: ReactNode;
  children: ReactNode;
}

/**
 * The app frame, shared by the (workspace) and (utility) route groups.
 *
 * AI Guru LiquidGlass layout:
 *   - Top: HeaderBar with logo, title, search, avatar
 *   - Center: Full-width content area
 *   - Bottom: FloatingDock navigation (desktop) or tab bar (mobile)
 *   - Dedicated LiquidGlass HistoryDrawer accessible from the dock
 */
export default function AppShell({ sidebar, children }: AppShellProps) {
  const { t } = useTranslation();
  const pathname = usePathname();
  const { isMobile } = useDevice();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);

  const close = useCallback(() => {
    setDrawerOpen(false);
    setHistoryOpen(false);
  }, []);

  // Auto-close on route change
  const [trackedPathname, setTrackedPathname] = useState(pathname);
  if (trackedPathname !== pathname) {
    setTrackedPathname(pathname);
    setDrawerOpen(false);
    setHistoryOpen(false);
  }

  useEffect(() => {
    if (!drawerOpen && !historyOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setDrawerOpen(false);
        setHistoryOpen(false);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [drawerOpen, historyOpen]);

  return (
    <SidebarDrawerContext.Provider value={{ close }}>
      <div className="flex flex-col h-dvh overflow-hidden bg-[var(--background)]" style={{ backgroundImage: 'var(--canvas-gradient)', backgroundAttachment: 'fixed' }}>
        {/* Header */}
        <HeaderBar />

        {/* Dedicated LiquidGlass History Drawer */}
        <HistoryDrawer
          isOpen={historyOpen}
          onClose={close}
        />

        {/* Mobile sidebar drawer (legacy support) */}
        {isMobile && drawerOpen && (
          <>
            <div
              onClick={close}
              aria-hidden
              className="fixed inset-0 z-40 bg-[var(--overlay)]"
            />
            <div
              className="fixed inset-y-0 left-0 z-50 w-[280px] surface-glass-elevated shadow-xl overflow-y-auto"
              style={{ borderRadius: '0 1rem 1rem 0' }}
            >
              {sidebar}
            </div>
          </>
        )}

        {/* Main content */}
        <main className="flex-1 min-h-0 overflow-hidden pb-16 md:pb-20">
          {children}
        </main>

        {/* Floating Dock Navigation */}
        <FloatingDock
          onShowHistory={() => setHistoryOpen(!historyOpen)}
        />
      </div>
    </SidebarDrawerContext.Provider>
  );
}
