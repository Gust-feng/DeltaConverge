type ScannerInstallTool = {
  name: string;
  url: string;
  description: string;
  command?: string;
  note?: string;
};

type ScannerInstallGroup = {
  title: string;
  languages: string[];
  tools: ScannerInstallTool[];
};

export const scannerInstallGroups: ScannerInstallGroup[] = [
  {
    title: "Python · Pylint / Flake8 / mypy",
    languages: ["python"],
    tools: [
      {
        name: "Pylint",
        url: "https://pylint.readthedocs.io/en/latest/user_guide/installation/index.html",
        description: "检查 Python 代码质量、常见错误和编码规范。需要后端所用的 Python 环境。",
        command: "python -m pip install pylint",
      },
      {
        name: "Flake8",
        url: "https://flake8.pycqa.org/en/latest/user/installation.html",
        description: "检查 Python 代码风格和常见错误。",
        command: "python -m pip install flake8",
      },
      {
        name: "mypy",
        url: "https://mypy.readthedocs.io/en/stable/getting_started.html",
        description: "检查 Python 静态类型。项目可能还需要对应依赖及类型声明包。",
        command: "python -m pip install mypy",
        note: "以上 python 必须指向启动后端的解释器；装到其他虚拟环境或 pipx 隔离环境中，服务无法检测到。",
      },
    ],
  },
  {
    title: "JavaScript / TypeScript · ESLint / tsc",
    languages: ["javascript", "typescript"],
    tools: [
      {
        name: "ESLint",
        url: "https://eslint.org/docs/latest/use/getting-started",
        description: "检查 JavaScript / TypeScript 代码。先安装官方支持版本的 Node.js 与 npm，再安装命令行工具。",
        command: "npm install -g eslint",
        note: "按 ESLint 官方说明为项目准备配置和所需插件。仅安装项目依赖中的 ESLint，服务可能无法发现；全局可执行目录需加入 PATH。",
      },
      {
        name: "TypeScript（tsc）",
        url: "https://www.typescriptlang.org/download/",
        description: "提供 TypeScript 类型检查器，命令名为 tsc。需要 Node.js 与 npm。",
        command: "npm install -g typescript",
        note: "确保 tsc 可从启动后端的环境中运行，并为项目准备依赖和合适的 tsconfig.json。",
      },
    ],
  },
  {
    title: "Java · Checkstyle / PMD",
    languages: ["java"],
    tools: [
      {
        name: "Checkstyle",
        url: "https://checkstyle.org/cmdline.html",
        description: "检查 Java 编码规范。按官方说明下载发行包，并安装与该版本匹配的 Java 运行环境。",
        note: "当前集成查找 PATH 中的 checkstyle 命令。只有 JAR 或 Maven 插件无法被发现，需要可执行入口；还需在扫描器配置或启动包装脚本中提供规则文件（-c）。",
      },
      {
        name: "PMD 7",
        url: "https://docs.pmd-code.org/latest/pmd_userdocs_installation.html",
        description: "检查 Java 代码中的常见缺陷。下载 PMD 7 发行包，安装所需 Java 环境，将发行包的 bin 目录加入 PATH。",
        note: "当前集成使用 pmd check 命令，请使用兼容的 PMD 7 版本；还需在扫描器配置或启动包装脚本中提供规则集（-R）。",
      },
    ],
  },
  {
    title: "Go · go vet / golangci-lint",
    languages: ["go"],
    tools: [
      {
        name: "go vet",
        url: "https://go.dev/doc/install",
        description: "检查 Go 代码中的可疑结构。下载安装 Go SDK 后即可使用，无需单独安装 go vet。",
        command: "go version\ngo vet ./...",
        note: "先确认 go 命令在 PATH 中，再在项目目录运行 go vet 验证；项目需要准备好 Go 模块及依赖。",
      },
      {
        name: "golangci-lint v1",
        url: "https://github.com/golangci/golangci-lint/releases/tag/v1.64.8",
        description: "聚合多种 Go 检查器。当前集成使用 v1 命令格式，请从官方发行页选择与操作系统匹配的 v1.64.8 包，或在兼容的 Go 环境中执行下方命令。",
        command: "go install github.com/golangci/golangci-lint/cmd/golangci-lint@v1.64.8",
        note: "将解压后的可执行目录，或 go install 使用的 GOBIN（默认 GOPATH/bin）加入 PATH。请勿直接安装 v2；项目所用 Go 版本也需与工具支持范围兼容。",
      },
    ],
  },
  {
    title: "Ruby · RuboCop",
    languages: ["ruby"],
    tools: [
      {
        name: "RuboCop",
        url: "https://docs.rubocop.org/rubocop/installation.html",
        description: "检查 Ruby 代码规范和常见问题。先安装 Ruby 与 RubyGems。",
        command: "gem install rubocop",
        note: "将 gem 可执行目录加入 PATH，确保后端可以直接运行 rubocop；仅通过项目的 bundle exec 可用时，服务可能无法检测到。",
      },
    ],
  },
  {
    title: "多语言 · Semgrep",
    languages: ["python", "javascript", "typescript", "java", "go", "ruby", "c", "cpp", "csharp", "rust", "kotlin", "swift", "php", "scala"],
    tools: [
      {
        name: "Semgrep",
        url: "https://semgrep.dev/docs/getting-started/",
        description: "使用规则匹配多种语言的代码问题。请先确认官方支持的操作系统与 Python 版本，再安装到后端所用的 Python 环境。",
        command: "python -m pip install semgrep",
        note: "原生 Windows 的可用性取决于发行包和扫描引擎支持；如需 WSL 或容器，请将后端与扫描器部署在同一环境。检测到 Python 模块不代表引擎一定能运行；默认自动规则可能需要联网下载。",
      },
    ],
  },
];
