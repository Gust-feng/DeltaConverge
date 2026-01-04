
import re
import os
import requests
from typing import Dict, Any, Optional

def parse_pr_url(url: str) -> Dict[str, Any]:
    """
    Parses a GitHub PR URL to extract owner, repo, and pr_number.
    
    Args:
        url: The GitHub PR URL (e.g., https://github.com/owner/repo/pull/123)
        
    Returns:
        Dict containing 'owner', 'repo', 'pr_number'.
        
    Raises:
        ValueError: If the URL is invalid.
    """
    # Remove trailing slash
    url = url.rstrip('/')
    
    # Matching simple pattern: github.com/owner/repo/pull/number
    # Also handles potential 'https://' or 'http://' or no protocol
    pattern = r"github\.com[/:](?P<owner>[^/]+)/(?P<repo>[^/]+)/pull/(?P<number>\d+)"
    match = re.search(pattern, url)
    
    if not match:
        raise ValueError(f"Invalid GitHub PR URL: {url}")
        
    return {
        "owner": match.group("owner"),
        "repo": match.group("repo"),
        "pr_number": int(match.group("number"))
    }

def fetch_pr_info(owner: str, repo: str, pr_number: int) -> Dict[str, Any]:
    """
    Fetches PR details from GitHub API.
    
    Args:
        owner: Repository owner.
        repo: Repository name.
        pr_number: Pull Request number.
        
    Returns:
        Dict containing PR details (title, body, base_sha, head_sha, etc.).
    """
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    headers = {
        "Accept": "application/vnd.github.v3+json"
    }
    if token:
        headers["Authorization"] = f"token {token}"
        
    api_url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}"
    
    try:
        resp = requests.get(api_url, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        
        return {
            "owner": owner,
            "repo": repo,
            "pr_number": pr_number,
            "title": data.get("title", ""),
            "body": data.get("body", ""),
            "state": data.get("state", ""),
            "merged": data.get("merged", False),
            "files_count": data.get("changed_files", 0),
            "additions": data.get("additions", 0),
            "deletions": data.get("deletions", 0),
            "base_sha": data["base"]["sha"],
            "head_sha": data["head"]["sha"],
            "base_ref": data["base"]["ref"],
            "head_ref": data["head"]["ref"],
            "html_url": data.get("html_url", "")
        }
    except requests.exceptions.RequestException as e:
        # If 404/403, might be private repo or rate limit
        msg = f"Failed to fetch PR info: {str(e)}"
        if resp is not None:
             msg += f" (Status: {resp.status_code})"
             try:
                 msg += f" Body: {resp.text}"
             except: 
                 pass
        raise RuntimeError(msg)


def _get_github_token() -> Optional[str]:
    """获取GitHub Token。
    
    按优先级尝试：
    1. GITHUB_TOKEN 环境变量
    2. GH_TOKEN 环境变量
    3. gh CLI (gh auth token)
    
    Returns:
        Token字符串，如果未配置则返回None
    """
    # 尝试环境变量
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        return token
    
    # 尝试从 gh CLI 获取
    try:
        import subprocess
        result = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    
    return None


def _get_auth_headers() -> Dict[str, str]:
    """获取GitHub API认证头。"""
    headers = {
        "Accept": "application/vnd.github.v3+json"
    }
    token = _get_github_token()
    if token:
        headers["Authorization"] = f"token {token}"
    return headers


def create_pull_request(
    owner: str,
    repo: str,
    title: str,
    head: str,
    base: str,
    body: Optional[str] = None,
    draft: bool = False,
    maintainer_can_modify: bool = True
) -> Dict[str, Any]:
    """
    通过GitHub API创建Pull Request。
    
    Args:
        owner: 仓库所有者
        repo: 仓库名称
        title: PR标题
        head: 源分支（包含变更的分支）
        base: 目标分支（要合并到的分支）
        body: PR描述（可选）
        draft: 是否创建为草稿PR
        maintainer_can_modify: 是否允许维护者修改
        
    Returns:
        Dict包含创建的PR信息（number, html_url, state等）
        
    Raises:
        RuntimeError: 如果Token未配置或API调用失败
    """
    token = _get_github_token()
    if not token:
        raise RuntimeError(
            "GitHub Token未配置。请设置GITHUB_TOKEN环境变量。"
            "Token需要具有'repo'权限才能创建PR。"
        )
    
    headers = _get_auth_headers()
    api_url = f"https://api.github.com/repos/{owner}/{repo}/pulls"
    
    payload = {
        "title": title,
        "head": head,
        "base": base,
        "maintainer_can_modify": maintainer_can_modify,
    }
    
    if body:
        payload["body"] = body
    if draft:
        payload["draft"] = draft
    
    resp = None
    try:
        resp = requests.post(api_url, headers=headers, json=payload, timeout=30)
        
        # 处理特定错误
        if resp.status_code == 401:
            raise RuntimeError("GitHub认证失败。请检查Token是否有效。")
        if resp.status_code == 403:
            error_msg = resp.json().get("message", "")
            raise RuntimeError(f"GitHub权限不足: {error_msg}。请确保Token具有'repo'权限。")
        if resp.status_code == 404:
            raise RuntimeError(f"仓库 {owner}/{repo} 不存在或无访问权限。")
        if resp.status_code == 422:
            # 通常是验证错误，例如已存在相同的PR
            error_data = resp.json()
            errors = error_data.get("errors", [])
            if errors:
                error_msgs = [e.get("message", str(e)) for e in errors]
                raise RuntimeError(f"创建PR失败: {'; '.join(error_msgs)}")
            raise RuntimeError(f"创建PR失败: {error_data.get('message', '验证错误')}")
        
        resp.raise_for_status()
        data = resp.json()
        
        return {
            "success": True,
            "number": data.get("number"),
            "html_url": data.get("html_url"),
            "state": data.get("state"),
            "title": data.get("title"),
            "head": data.get("head", {}).get("ref"),
            "base": data.get("base", {}).get("ref"),
            "created_at": data.get("created_at"),
            "draft": data.get("draft", False),
        }
        
    except requests.exceptions.Timeout:
        raise RuntimeError("GitHub API请求超时，请稍后重试。")
    except requests.exceptions.ConnectionError:
        raise RuntimeError("无法连接到GitHub API，请检查网络连接。")
    except requests.exceptions.RequestException as e:
        msg = f"创建PR失败: {str(e)}"
        if resp is not None:
            try:
                error_data = resp.json()
                msg += f" - {error_data.get('message', resp.text)}"
            except:
                msg += f" - {resp.text}"
        raise RuntimeError(msg)


def add_pr_comment(
    owner: str,
    repo: str,
    pr_number: int,
    body: str
) -> Dict[str, Any]:
    """
    向PR添加评论。
    
    Args:
        owner: 仓库所有者
        repo: 仓库名称
        pr_number: PR编号
        body: 评论内容
        
    Returns:
        Dict包含评论信息
        
    Raises:
        RuntimeError: 如果Token未配置或API调用失败
    """
    token = _get_github_token()
    if not token:
        raise RuntimeError("GitHub Token未配置。请设置GITHUB_TOKEN环境变量。")
    
    headers = _get_auth_headers()
    api_url = f"https://api.github.com/repos/{owner}/{repo}/issues/{pr_number}/comments"
    
    payload = {"body": body}
    
    resp = None
    try:
        resp = requests.post(api_url, headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        
        return {
            "success": True,
            "id": data.get("id"),
            "html_url": data.get("html_url"),
            "created_at": data.get("created_at"),
        }
        
    except requests.exceptions.RequestException as e:
        msg = f"添加评论失败: {str(e)}"
        if resp is not None:
            try:
                error_data = resp.json()
                msg += f" - {error_data.get('message', resp.text)}"
            except:
                pass
        raise RuntimeError(msg)


def list_repo_branches(owner: str, repo: str, per_page: int = 30) -> list:
    """
    列出仓库的分支。
    
    Args:
        owner: 仓库所有者
        repo: 仓库名称
        per_page: 每页返回数量
        
    Returns:
        分支名称列表
    """
    headers = _get_auth_headers()
    api_url = f"https://api.github.com/repos/{owner}/{repo}/branches"
    params = {"per_page": per_page}
    
    resp = None
    try:
        resp = requests.get(api_url, headers=headers, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return [b.get("name") for b in data if b.get("name")]
    except requests.exceptions.RequestException:
        return []


def get_default_branch(owner: str, repo: str) -> Optional[str]:
    """
    获取仓库的默认分支。
    
    Args:
        owner: 仓库所有者
        repo: 仓库名称
        
    Returns:
        默认分支名称，如果失败则返回None
    """
    headers = _get_auth_headers()
    api_url = f"https://api.github.com/repos/{owner}/{repo}"
    
    try:
        resp = requests.get(api_url, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return data.get("default_branch")
    except requests.exceptions.RequestException:
        return None


def create_pr_review(
    owner: str,
    repo: str,
    pr_number: int,
    body: str,
    comments: list = None,
    event: str = "COMMENT"
) -> Dict[str, Any]:
    """
    创建PR Review，支持行级评论。
    
    Args:
        owner: 仓库所有者
        repo: 仓库名称
        pr_number: PR编号
        body: Review总体描述
        comments: 行级评论列表，每个元素包含:
            - path: 文件路径
            - line: 行号（新文件中的行号）
            - body: 评论内容
            - side: "LEFT"(旧文件) 或 "RIGHT"(新文件)，默认"RIGHT"
        event: Review事件类型，"COMMENT"(纯评论), "APPROVE"(批准), "REQUEST_CHANGES"(请求修改)
        
    Returns:
        Dict包含Review信息
        
    Raises:
        RuntimeError: 如果API调用失败
    """
    token = _get_github_token()
    if not token:
        raise RuntimeError("GitHub Token未配置。请设置GITHUB_TOKEN环境变量。")
    
    headers = _get_auth_headers()
    api_url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/reviews"
    
    payload = {
        "body": body,
        "event": event
    }
    
    if comments:
        # 格式化评论
        formatted_comments = []
        for c in comments:
            comment = {
                "path": c.get("path", ""),
                "body": c.get("body", ""),
            }
            # 使用line参数（简单模式）
            if c.get("line"):
                comment["line"] = c["line"]
                comment["side"] = c.get("side", "RIGHT")
            # 或使用start_line + line（多行模式）
            elif c.get("start_line") and c.get("end_line"):
                comment["start_line"] = c["start_line"]
                comment["line"] = c["end_line"]
                comment["side"] = c.get("side", "RIGHT")
            
            if comment.get("path") and comment.get("body"):
                formatted_comments.append(comment)
        
        if formatted_comments:
            payload["comments"] = formatted_comments
    
    resp = None
    try:
        resp = requests.post(api_url, headers=headers, json=payload, timeout=60)
        
        if resp.status_code == 422:
            error_data = resp.json()
            errors = error_data.get("errors", [])
            if errors:
                error_msgs = [str(e) for e in errors]
                raise RuntimeError(f"创建Review失败: {'; '.join(error_msgs)}")
            raise RuntimeError(f"创建Review失败: {error_data.get('message', '验证错误')}")
        
        resp.raise_for_status()
        data = resp.json()
        
        return {
            "success": True,
            "id": data.get("id"),
            "state": data.get("state"),
            "html_url": data.get("html_url"),
            "submitted_at": data.get("submitted_at"),
        }
        
    except requests.exceptions.RequestException as e:
        msg = f"创建Review失败: {str(e)}"
        if resp is not None:
            try:
                error_data = resp.json()
                msg += f" - {error_data.get('message', resp.text)}"
            except:
                pass
        raise RuntimeError(msg)


def create_single_review_comment(
    owner: str,
    repo: str,
    pr_number: int,
    body: str,
    path: str,
    line: int,
    side: str = "RIGHT",
    commit_id: str = None
) -> Dict[str, Any]:
    """
    创建单条Review评论（用于逐条尝试）。
    
    Args:
        owner: 仓库所有者
        repo: 仓库名称
        pr_number: PR编号
        body: 评论内容
        path: 文件路径
        line: 行号
        side: "LEFT"或"RIGHT"
        commit_id: 可选，提交ID
        
    Returns:
        Dict: 成功返回评论对象，失败抛出异常
    """
    token = _get_github_token()
    headers = _get_auth_headers()
    api_url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/comments"
    
    payload = {
        "body": body,
        "path": path,
        "line": line,
        "side": side
    }
    if commit_id:
        payload["commit_id"] = commit_id
        
    resp = requests.post(api_url, headers=headers, json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()


def format_review_comments_from_suggestions(
    suggestions: list,
    include_severity: bool = True
) -> tuple:
    """
    将审查建议格式化为GitHub Review评论格式。
    
    Args:
        suggestions: 审查建议列表，来自parse_review_report_issues
        include_severity: 是否在评论中包含严重性标记
        
    Returns:
        (body, comments) 元组:
            - body: Review总体描述
            - comments: 格式化后的行级评论列表
    """
    if not suggestions:
        return "审查完成，未发现问题。", []
    
    comments = []
    stats = {"error": 0, "warning": 0, "info": 0}
    
    for s in suggestions:
        # 获取文件路径
        file_path = s.get("file") or s.get("file_path") or ""
        if not file_path:
            continue
        
        # 清理路径前缀
        file_path = file_path.lstrip("/").lstrip("a/").lstrip("b/")
        
        # 获取行号
        line = s.get("line") or s.get("start_line") or 0
        try:
            line = int(line)
        except:
            line = 0
        
        if line <= 0:
            continue
        
        # 获取严重性
        severity = (s.get("severity") or s.get("type") or "info").lower()
        if severity in ("error", "critical", "高"):
            severity_icon = "🔴"
            stats["error"] += 1
        elif severity in ("warning", "warn", "中"):
            severity_icon = "🟡"
            stats["warning"] += 1
        else:
            severity_icon = "🔵"
            stats["info"] += 1
        
        # 构建评论内容
        message = s.get("message") or s.get("description") or ""
        suggestion_text = s.get("suggestion") or ""
        
        body_parts = []
        if include_severity:
            body_parts.append(f"**{severity_icon} {severity.upper()}**")
        body_parts.append(message)
        if suggestion_text:
            body_parts.append(f"\n**建议**: {suggestion_text}")
        
        comments.append({
            "path": file_path,
            "line": line,
            "body": "\n\n".join(body_parts) if len(body_parts) > 1 else body_parts[0],
            "side": "RIGHT"
        })
    
    # 生成总体描述
    total = stats["error"] + stats["warning"] + stats["info"]
    body = f"""## 🤖 AI 代码审查报告

本次审查共发现 **{total}** 个问题：
- 🔴 严重: {stats['error']}
- 🟡 警告: {stats['warning']}
- 🔵 信息: {stats['info']}

---
*由 DeltaConverge 代码审查系统自动生成*
"""
    
    return body, comments


