"""项目上下文API模块。

提供项目信息查询、文件树、依赖等功能。
"""

from __future__ import annotations

import json
import os
import struct
from pathlib import Path
from typing import Any, Dict, List, Optional

from Agent.core.context.runtime_context import get_project_root, set_project_root
from Agent.DIFF.git_operations import run_git


class ProjectAPI:
    """项目上下文API（静态方法接口）。"""
    
    @staticmethod
    def _get_git_index_path(root_path: Path) -> Optional[Path]:
        git_path = root_path / ".git"
        if git_path.is_dir():
            index_path = git_path / "index"
            if index_path.exists():
                return index_path
            return None
        if git_path.is_file():
            try:
                content = git_path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                return None
            gitdir = None
            for line in content.splitlines():
                s = line.strip()
                if s.lower().startswith("gitdir:"):
                    gitdir = s[7:].strip()
                    break
            if not gitdir:
                return None
            p = Path(gitdir)
            if not p.is_absolute():
                p = (root_path / p).resolve()
            else:
                p = p.resolve()
            index_path = p / "index"
            if index_path.exists():
                return index_path
        return None

    @staticmethod
    def _read_git_index_count(index_path: Path) -> Optional[int]:
        try:
            with open(index_path, "rb") as f:
                header = f.read(12)
            if len(header) != 12:
                return None
            signature, version, count = struct.unpack(">4sII", header)
            if signature != b"DIRC":
                return None
            if version not in (2, 3, 4):
                return None
            return int(count)
        except Exception:
            return None

    @staticmethod
    def _read_git_index_paths(index_path: Path, max_entries: int = 500) -> List[str]:
        results: List[str] = []
        try:
            with open(index_path, "rb") as f:
                max_bytes_per_entry = 4096
                header = f.read(12)
                if len(header) != 12:
                    return results
                signature, version, entry_count = struct.unpack(">4sII", header)
                if signature != b"DIRC" or version not in (2, 3):
                    return results
                limit = min(int(entry_count), int(max_entries))
                for _ in range(limit):
                    base = f.read(62)
                    if len(base) != 62:
                        break
                    flags = struct.unpack(">H", base[60:62])[0]
                    entry_len = 62
                    if flags & 0x4000:
                        ext = f.read(2)
                        if len(ext) != 2:
                            break
                        entry_len += 2
                    name_len = flags & 0x0FFF
                    if name_len != 0x0FFF:
                        name = f.read(name_len)
                        if len(name) != name_len:
                            break
                        nul = f.read(1)
                        if len(nul) != 1:
                            break
                        entry_len += name_len + 1
                    else:
                        chunks: List[bytes] = []
                        read_bytes = 0
                        while True:
                            b = f.read(1)
                            if not b:
                                break
                            entry_len += 1
                            read_bytes += 1
                            if read_bytes > max_bytes_per_entry:
                                return results
                            if b == b"\x00":
                                break
                            chunks.append(b)
                        name = b"".join(chunks)
                    pad = (8 - (entry_len % 8)) % 8
                    if pad:
                        f.read(pad)
                    results.append(name.decode("utf-8", errors="replace"))
        except Exception:
            return results
        return results
     
    @staticmethod
    def get_project_info(project_root: Optional[str] = None) -> Dict[str, Any]:
        """获取项目基本信息。
        
        Args:
            project_root: 项目根目录，None则使用当前设置
            
        Returns:
            Dict: {
                "project_name": str,
                "project_path": str,
                "is_git_repo": bool,
                "git_branch": str | None,
                "file_count": int,
                "has_readme": bool,
                "detected_languages": List[str]
            }
        """
        root = project_root or get_project_root() or os.getcwd()
        root_path = Path(root).resolve()
        
        info = {
            "project_name": root_path.name,
            "project_path": str(root_path),
            "is_git_repo": False,
            "git_branch": None,
            "file_count": 0,
            "has_readme": False,
            "detected_languages": [],
        }
        
        # 检查Git状态
        try:
            branch = run_git("rev-parse", "--abbrev-ref", "HEAD", cwd=root).strip()
            info["is_git_repo"] = True
            info["git_branch"] = branch
        except Exception:
            pass
        
        # 检查README
        readme_files = ["README.md", "readme.md", "README.rst", "README.txt"]
        for readme in readme_files:
            if (root_path / readme).exists():
                info["has_readme"] = True
                break
        
        # 检测语言
        languages = set()
        ext_to_lang = {
            ".py": "Python",
            ".js": "JavaScript",
            ".ts": "TypeScript",
            ".jsx": "React",
            ".tsx": "React/TypeScript",
            ".java": "Java",
            ".go": "Go",
            ".rs": "Rust",
            ".cpp": "C++",
            ".c": "C",
            ".rb": "Ruby",
            ".php": "PHP",
        }
        
        if info["is_git_repo"]:
            index_path = ProjectAPI._get_git_index_path(root_path)
            if index_path is not None:
                count = ProjectAPI._read_git_index_count(index_path)
                if isinstance(count, int):
                    info["file_count"] = count
                for f in ProjectAPI._read_git_index_paths(index_path, max_entries=500):
                    ext = Path(f).suffix.lower()
                    if ext in ext_to_lang:
                        languages.add(ext_to_lang[ext])
        else:
            try:
                count = 0
                skipped_dirs = {
                    ".git",
                    "node_modules",
                    "__pycache__",
                    "venv",
                    ".venv",
                    "dist",
                    "build",
                    ".idea",
                    ".vscode",
                }
                for dirpath, dirnames, filenames in os.walk(root_path, topdown=True, followlinks=False):
                    try:
                        dirnames[:] = [
                            d
                            for d in dirnames
                            if not d.startswith(".") and d not in skipped_dirs
                        ]
                    except Exception:
                        pass

                    for filename in filenames:
                        if filename.startswith("."):
                            continue
                        count += 1
                        ext = Path(filename).suffix.lower()
                        if ext in ext_to_lang:
                            languages.add(ext_to_lang[ext])
                        if count >= 1000:
                            break
                    if count >= 1000:
                        break
                info["file_count"] = count
            except Exception:
                pass
        
        info["detected_languages"] = sorted(languages)
        return info
    
    @staticmethod
    def get_file_tree(
        project_root: Optional[str] = None,
        max_depth: int = 3,
        include_hidden: bool = False,
    ) -> Dict[str, Any]:
        """获取项目文件树结构。
        
        Args:
            project_root: 项目根目录
            max_depth: 最大深度
            include_hidden: 是否包含隐藏文件
            
        Returns:
            Dict: 嵌套的文件树结构
        """
        root = project_root or get_project_root() or os.getcwd()
        root_path = Path(root).resolve()
        
        def build_tree(path: Path, depth: int) -> Optional[Dict[str, Any]]:
            if depth > max_depth:
                return {"__truncated__": True}
            
            if not path.is_dir():
                return None
            
            result = {}
            try:
                entries = sorted(path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
                for entry in entries[:100]:  # 限制每层数量
                    if not include_hidden and entry.name.startswith("."):
                        continue
                    if entry.name in {"__pycache__", "node_modules", ".git", "venv", ".venv"}:
                        continue
                    
                    if entry.is_dir():
                        subtree = build_tree(entry, depth + 1)
                        if subtree is not None:
                            result[entry.name + "/"] = subtree
                    else:
                        result[entry.name] = None
            except PermissionError:
                pass
            
            return result
        
        return {
            "root": str(root_path),
            "tree": build_tree(root_path, 1),
        }
    
    @staticmethod
    def get_readme_content(project_root: Optional[str] = None) -> Dict[str, Any]:
        """获取README文件内容。
        
        Args:
            project_root: 项目根目录
            
        Returns:
            Dict: {"found": bool, "filename": str, "content": str}
        """
        root = project_root or get_project_root() or os.getcwd()
        root_path = Path(root).resolve()
        
        readme_files = ["README.md", "readme.md", "README.rst", "README.txt", "README"]
        
        for readme in readme_files:
            readme_path = root_path / readme
            if readme_path.exists() and readme_path.is_file():
                try:
                    content = readme_path.read_text(encoding="utf-8", errors="ignore")
                    return {
                        "found": True,
                        "filename": readme,
                        "content": content[:10000],  # 限制大小
                    }
                except Exception as e:
                    return {
                        "found": True,
                        "filename": readme,
                        "content": "",
                        "error": str(e),
                    }
        
        return {
            "found": False,
            "filename": None,
            "content": None,
        }
    
    @staticmethod
    def get_dependencies(project_root: Optional[str] = None) -> Dict[str, Any]:
        """获取项目依赖信息。
        
        Args:
            project_root: 项目根目录
            
        Returns:
            Dict: 各依赖文件的内容
        """
        root = project_root or get_project_root() or os.getcwd()
        root_path = Path(root).resolve()
        
        result = {}
        
        # Python 依赖
        req = root_path / "requirements.txt"
        if req.exists():
            try:
                content = req.read_text(encoding="utf-8")
                deps = [
                    line.strip() for line in content.splitlines()
                    if line.strip() and not line.strip().startswith("#")
                ]
                result["requirements.txt"] = {
                    "type": "python",
                    "dependencies": deps,
                    "count": len(deps),
                }
            except Exception as e:
                result["requirements.txt"] = {"error": str(e)}
        
        # pyproject.toml
        pyproject = root_path / "pyproject.toml"
        if pyproject.exists():
            try:
                content = pyproject.read_text(encoding="utf-8")
                result["pyproject.toml"] = {
                    "type": "python",
                    "content_preview": content[:2000],
                }
            except Exception as e:
                result["pyproject.toml"] = {"error": str(e)}
        
        # package.json
        pkg = root_path / "package.json"
        if pkg.exists():
            try:
                data = json.loads(pkg.read_text(encoding="utf-8"))
                deps = data.get("dependencies", {})
                dev_deps = data.get("devDependencies", {})
                result["package.json"] = {
                    "type": "npm",
                    "dependencies": deps,
                    "devDependencies": dev_deps,
                    "dep_count": len(deps),
                    "dev_dep_count": len(dev_deps),
                }
            except Exception as e:
                result["package.json"] = {"error": str(e)}
        
        # go.mod
        gomod = root_path / "go.mod"
        if gomod.exists():
            try:
                content = gomod.read_text(encoding="utf-8")
                result["go.mod"] = {
                    "type": "go",
                    "content_preview": content[:2000],
                }
            except Exception as e:
                result["go.mod"] = {"error": str(e)}
        
        # Cargo.toml
        cargo = root_path / "Cargo.toml"
        if cargo.exists():
            try:
                content = cargo.read_text(encoding="utf-8")
                result["Cargo.toml"] = {
                    "type": "rust",
                    "content_preview": content[:2000],
                }
            except Exception as e:
                result["Cargo.toml"] = {"error": str(e)}
        
        return result
    
    @staticmethod
    def get_git_info(project_root: Optional[str] = None) -> Dict[str, Any]:
        """获取Git仓库信息。
        
        Args:
            project_root: 项目根目录
            
        Returns:
            Dict: Git相关信息
        """
        root = project_root or get_project_root() or os.getcwd()
        
        result = {
            "is_git_repo": False,
            "current_branch": None,
            "remote_url": None,
            "recent_commits": [],
            "local_branches": [],
            "has_uncommitted_changes": False,
        }
        
        try:
            # 当前分支
            branch = run_git("rev-parse", "--abbrev-ref", "HEAD", cwd=root).strip()
            result["is_git_repo"] = True
            result["current_branch"] = branch
            
            # 远程URL
            try:
                remote = run_git("remote", "get-url", "origin", cwd=root).strip()
                result["remote_url"] = remote
            except Exception:
                pass
            
            # 最近提交
            try:
                log_output = run_git("log", "-n10", "--pretty=format:%h|%s|%an|%ar", cwd=root)
                commits = []
                for line in log_output.strip().split("\n"):
                    if line and "|" in line:
                        parts = line.split("|", 3)
                        if len(parts) >= 4:
                            commits.append({
                                "hash": parts[0],
                                "message": parts[1],
                                "author": parts[2],
                                "time_ago": parts[3],
                            })
                result["recent_commits"] = commits
            except Exception:
                pass
            
            # 本地分支
            try:
                branches_output = run_git("branch", "--list", cwd=root)
                branches = [
                    b.strip().lstrip("* ") for b in branches_output.split("\n")
                    if b.strip()
                ]
                result["local_branches"] = branches
            except Exception:
                pass
            
            # 未提交变更
            try:
                status = run_git("status", "--porcelain", cwd=root)
                result["has_uncommitted_changes"] = bool(status.strip())
            except Exception:
                pass
            
        except Exception:
            pass
        
        return result
    
    @staticmethod
    def search_files(
        query: str,
        project_root: Optional[str] = None,
        file_pattern: Optional[str] = None,
        max_results: int = 50,
    ) -> Dict[str, Any]:
        """在项目中搜索文件内容。
        
        Args:
            query: 搜索关键词
            project_root: 项目根目录
            file_pattern: 文件名模式过滤
            max_results: 最大返回条数
            
        Returns:
            Dict: {"matches": List[{...}], "count": int}
        """
        root = project_root or get_project_root() or os.getcwd()
        
        try:
            args = ["grep", "-n", "--no-color"]
            if file_pattern:
                args.extend(["--", file_pattern])
            args.append(query)
            
            output = run_git(*args[1:], cwd=root)  # run_git 第一个参数是命令
            
            matches = []
            for line in output.split("\n"):
                if ":" not in line:
                    continue
                parts = line.split(":", 2)
                if len(parts) >= 3:
                    matches.append({
                        "file": parts[0],
                        "line": int(parts[1]) if parts[1].isdigit() else 0,
                        "content": parts[2].strip()[:200],
                    })
                if len(matches) >= max_results:
                    break
            
            return {
                "query": query,
                "matches": matches,
                "count": len(matches),
            }
        except Exception as e:
            return {
                "query": query,
                "matches": [],
                "count": 0,
                "error": str(e),
            }
    
    @staticmethod
    def set_current_project(project_root: str) -> Dict[str, Any]:
        """设置当前项目根目录。
        
        Args:
            project_root: 项目根目录路径
            
        Returns:
            Dict: {"success": bool, "project_root": str}
        """
        path = Path(project_root).resolve()
        if not path.is_dir():
            return {
                "success": False,
                "error": f"Directory not found: {project_root}",
            }
        
        set_project_root(str(path))
        return {
            "success": True,
            "project_root": str(path),
        }
    
    @staticmethod
    def get_current_project() -> Dict[str, Any]:
        """获取当前项目根目录。
        
        Returns:
            Dict: {"project_root": str | None}
        """
        root = get_project_root()
        return {
            "project_root": root,
        }


__all__ = [
    "ProjectAPI",
]
