import { create } from "zustand";
import { availableModel, reconcileModel } from "../lib/modelSelection";
import type {
  ActivePage,
  DiffMode,
  LayoutState,
  ModelGroup,
  ReportViewMode,
  ToolOption,
} from "../types";

const PROJECT_KEY = "selectedProjectRoot";

function readStoredProjectRoot(): string | null {
  try {
    return localStorage.getItem(PROJECT_KEY);
  } catch {
    return null;
  }
}

export type AppStore = {
  activePage: ActivePage;
  layoutState: LayoutState;
  projectRoot: string | null;
  sessionId: string | null;
  runId: string | null;
  model: string;
  availableGroups: ModelGroup[];
  tools: ToolOption[];
  selectedTools: string[];
  optionsLoading: boolean;
  optionsError: boolean;
  autoApprove: boolean;
  enableStaticScan: boolean;
  diffMode: DiffMode;
  currentDiffMode: string;
  commitFrom: string | null;
  commitTo: string;
  reportViewMode: ReportViewMode;
  historyDrawerOpen: boolean;
  modelManagementOpen: boolean;
  folderPickerOpen: boolean;
  runningSessionId: string | null;
  viewingHistory: boolean;

  setActivePage: (page: ActivePage) => void;
  setLayoutState: (state: LayoutState) => void;
  setProjectRoot: (root: string | null) => void;
  setSessionId: (id: string | null) => void;
  setRunId: (id: string | null) => void;
  setModel: (model: string) => void;
  setAvailableGroups: (groups: ModelGroup[]) => void;
  setTools: (tools: ToolOption[]) => void;
  setSelectedTools: (tools: string[]) => void;
  setOptionsState: (loading: boolean, error: boolean) => void;
  toggleTool: (name: string) => void;
  setAutoApprove: (value: boolean) => void;
  setEnableStaticScan: (value: boolean) => void;
  setDiffMode: (mode: DiffMode) => void;
  setCurrentDiffMode: (mode: string) => void;
  setCommitRange: (from: string | null, to: string) => void;
  setReportViewMode: (mode: ReportViewMode) => void;
  setHistoryDrawerOpen: (open: boolean) => void;
  toggleHistoryDrawer: () => void;
  setModelManagementOpen: (open: boolean) => void;
  setFolderPickerOpen: (open: boolean) => void;
  setRunningSessionId: (id: string | null) => void;
  setViewingHistory: (value: boolean) => void;
};

export const useAppStore = create<AppStore>((set, get) => ({
  activePage: "review",
  layoutState: "initial",
  projectRoot: readStoredProjectRoot(),
  sessionId: null,
  runId: null,
  model: "",
  availableGroups: [],
  tools: [],
  selectedTools: [],
  optionsLoading: true,
  optionsError: false,
  autoApprove: false,
  enableStaticScan: true,
  diffMode: "auto",
  currentDiffMode: "auto",
  commitFrom: null,
  commitTo: "HEAD",
  reportViewMode: "report",
  historyDrawerOpen: false,
  modelManagementOpen: false,
  folderPickerOpen: false,
  runningSessionId: null,
  viewingHistory: false,

  setActivePage: (activePage) => set({ activePage }),
  setLayoutState: (layoutState) => set({ layoutState }),
  setProjectRoot: (projectRoot) => {
    try {
      if (projectRoot) localStorage.setItem(PROJECT_KEY, projectRoot);
      else localStorage.removeItem(PROJECT_KEY);
    } catch {
      // 旧版同样忽略 localStorage 异常
    }
    set({ projectRoot });
  },
  setSessionId: (sessionId) => set({ sessionId }),
  setRunId: (runId) => set({ runId }),
  setModel: (model) => set({ model: availableModel(get().availableGroups, model)?.name ?? "" }),
  setAvailableGroups: (availableGroups) => set((state) => ({
    availableGroups,
    model: reconcileModel(availableGroups, state.model),
  })),
  setTools: (tools) => set({ tools }),
  setSelectedTools: (selectedTools) => set({ selectedTools }),
  setOptionsState: (optionsLoading, optionsError) => set({ optionsLoading, optionsError }),
  toggleTool: (name) => {
    const current = get().selectedTools;
    set({ selectedTools: current.includes(name) ? current.filter((item) => item !== name) : [...current, name] });
  },
  setAutoApprove: (autoApprove) => set({ autoApprove }),
  setEnableStaticScan: (enableStaticScan) => set({ enableStaticScan }),
  setDiffMode: (diffMode) => set({ diffMode }),
  setCurrentDiffMode: (currentDiffMode) => set({ currentDiffMode }),
  setCommitRange: (commitFrom, commitTo) => set({ commitFrom, commitTo }),
  setReportViewMode: (reportViewMode) => set({ reportViewMode }),
  setHistoryDrawerOpen: (historyDrawerOpen) => set({ historyDrawerOpen }),
  toggleHistoryDrawer: () => set({ historyDrawerOpen: !get().historyDrawerOpen }),
  setModelManagementOpen: (modelManagementOpen) => set({ modelManagementOpen }),
  setFolderPickerOpen: (folderPickerOpen) => set({ folderPickerOpen }),
  setRunningSessionId: (runningSessionId) => set({ runningSessionId }),
  setViewingHistory: (viewingHistory) => set({ viewingHistory }),
}));

export function getProjectName(projectRoot?: string | null): string {
  if (!projectRoot) return "";
  const trimmed = projectRoot.replace(/[\\/]+$/, "");
  const parts = trimmed.split(/[\\/]/);
  return parts[parts.length - 1] || trimmed;
}
