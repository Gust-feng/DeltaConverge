import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

export type ActivePage = "dashboard" | "review" | "diff" | "rule-growth" | "config";
export type ReviewLayoutState = "initial" | "running" | "completed" | "replay";
export type DiffMode = "auto" | "working" | "staged" | "pr" | "commit";
export type ReportView = "report" | "detail";

type AppState = {
  activePage: ActivePage;
  historyDrawerOpen: boolean;
  reviewLayoutState: ReviewLayoutState;
  selectedSessionId: string | null;
  sessionFilter: string;
  statusText: string;
  projectRoot: string;
  model: string;
  selectedTools: string[];
  autoApprove: boolean;
  enableStaticScan: boolean;
  diffMode: DiffMode;
  selectedDiffFile: string | null;
  selectedCommitFrom: string | null;
  selectedCommitTo: string;
  reportView: ReportView;
  question: string;
  qaAnswer: string;
  folderPickerOpen: boolean;
  setActivePage: (activePage: ActivePage) => void;
  setHistoryDrawerOpen: (open: boolean) => void;
  toggleHistoryDrawer: () => void;
  setReviewLayoutState: (state: ReviewLayoutState) => void;
  setSelectedSessionId: (sessionId: string | null) => void;
  setSessionFilter: (value: string) => void;
  setStatusText: (value: string) => void;
  setProjectRoot: (value: string) => void;
  setModel: (value: string) => void;
  setSelectedTools: (tools: string[]) => void;
  toggleTool: (tool: string) => void;
  setAutoApprove: (value: boolean) => void;
  setEnableStaticScan: (value: boolean) => void;
  setDiffMode: (value: DiffMode) => void;
  setSelectedDiffFile: (value: string | null) => void;
  setCommitRange: (from: string | null, to: string) => void;
  setReportView: (view: ReportView) => void;
  setQuestion: (value: string) => void;
  setQaAnswer: (value: string) => void;
  resetQA: () => void;
  setFolderPickerOpen: (open: boolean) => void;
};

export const useAppStore = create<AppState>()(
  persist(
    (set, get) => ({
      activePage: "review",
      historyDrawerOpen: false,
      reviewLayoutState: "initial",
      selectedSessionId: null,
      sessionFilter: "",
      statusText: "Idle",
      projectRoot: "",
      model: "auto",
      selectedTools: [],
      autoApprove: false,
      enableStaticScan: true,
      diffMode: "auto",
      selectedDiffFile: null,
      selectedCommitFrom: null,
      selectedCommitTo: "HEAD",
      reportView: "report",
      question: "",
      qaAnswer: "",
      folderPickerOpen: false,
      setActivePage: (activePage) => set({ activePage }),
      setHistoryDrawerOpen: (historyDrawerOpen) => set({ historyDrawerOpen }),
      toggleHistoryDrawer: () => set({ historyDrawerOpen: !get().historyDrawerOpen }),
      setReviewLayoutState: (reviewLayoutState) => set({ reviewLayoutState }),
      setSelectedSessionId: (selectedSessionId) => set({ selectedSessionId }),
      setSessionFilter: (sessionFilter) => set({ sessionFilter }),
      setStatusText: (statusText) => set({ statusText }),
      setProjectRoot: (projectRoot) => set({ projectRoot }),
      setModel: (model) => set({ model }),
      setSelectedTools: (selectedTools) => set({ selectedTools }),
      toggleTool: (tool) => {
        const current = get().selectedTools;
        set({
          selectedTools: current.includes(tool) ? current.filter((item) => item !== tool) : [...current, tool],
        });
      },
      setAutoApprove: (autoApprove) => set({ autoApprove }),
      setEnableStaticScan: (enableStaticScan) => set({ enableStaticScan }),
      setDiffMode: (diffMode) => set({ diffMode, selectedDiffFile: null }),
      setSelectedDiffFile: (selectedDiffFile) => set({ selectedDiffFile }),
      setCommitRange: (selectedCommitFrom, selectedCommitTo) =>
        set({ selectedCommitFrom, selectedCommitTo, selectedDiffFile: null }),
      setReportView: (reportView) => set({ reportView }),
      setQuestion: (question) => set({ question }),
      setQaAnswer: (qaAnswer) => set({ qaAnswer }),
      resetQA: () => set({ question: "", qaAnswer: "" }),
      setFolderPickerOpen: (folderPickerOpen) => set({ folderPickerOpen }),
    }),
    {
      name: "deltaconverge-legacy-workbench-v2",
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({
        activePage: state.activePage,
        projectRoot: state.projectRoot,
        model: state.model,
        selectedTools: state.selectedTools,
        autoApprove: state.autoApprove,
        enableStaticScan: state.enableStaticScan,
        diffMode: state.diffMode,
        selectedCommitFrom: state.selectedCommitFrom,
        selectedCommitTo: state.selectedCommitTo,
        reportView: state.reportView,
      }),
    }
  )
);
