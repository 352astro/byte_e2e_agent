"""
ShadowRepo — Dulwich-based shadow git repository for workspace snapshot & restore.

Coexists with the user's real .git repo, tracks the identical working tree.
Snapshot on every user message; restore to any commit to rewind workspace state.

Pattern adapted from Dulwich-test/demo.py.
"""

from __future__ import annotations

import os
import time
from io import BytesIO
from pathlib import Path
from typing import Any

from dulwich.diff import write_object_diff
from dulwich.diff_tree import tree_changes
from dulwich.ignore import IgnoreFilter, IgnoreFilterManager, get_xdg_config_home_path
from dulwich.index import Index, IndexEntry
from dulwich.objects import Blob, Commit
from dulwich.repo import Repo
from dulwich.walk import Walker

from agent.core.workspace import Workspace
from agent.paths import shadow_repo_dir
from app.core.config import AGENT_DATA_DIR


def _ensure_dir(p: str) -> None:
    Path(p).mkdir(parents=True, exist_ok=True)


def _walk_tree(
    store, tree_id: bytes, prefix: bytes = b""
) -> list[tuple[bytes, int, bytes]]:
    """Recursively collect all file entries from a tree, skipping directories."""
    import stat

    result: list[tuple[bytes, int, bytes]] = []
    tree = store[tree_id]
    for name, mode, sha in tree.iteritems():
        full = prefix + name
        if stat.S_ISDIR(mode):
            result.extend(_walk_tree(store, sha, full + b"/"))
        else:
            result.append((full, mode, sha))
    return result


# ── ShadowRepo ───────────────────────────────────────────


class ShadowRepo:
    """Per-session shadow git repo for workspace snapshots.

    workdir  = project workspace (the user's working directory)
    repodir  = path to bare repo, e.g. "PROJECT_ROOT/.agent/workspaces/{uuid}/.shadow-vcs"
    """

    @staticmethod
    def _branch_ref(session_id: str) -> bytes:
        return f"refs/heads/{session_id}".encode()

    def __init__(self, ws: Workspace) -> None:
        self._workdir = os.path.abspath(str(ws.root))
        self._repodir = os.path.abspath(str(shadow_repo_dir(ws.uuid)))

        # ── open or init bare repo ──────────────────────
        _ensure_dir(self._repodir)
        try:
            self._repo: Repo = Repo(self._repodir)
        except Exception:
            self._repo = Repo.init_bare(self._repodir)

        # ── ignore filters (gitignore + exclude) ────────
        global_filters: list[IgnoreFilter] = []
        for p in [
            os.path.join(self._workdir, ".git", "info", "exclude"),
            get_xdg_config_home_path("git", "ignore"),
        ]:
            try:
                global_filters.append(IgnoreFilter.from_path(p))
            except FileNotFoundError:
                pass
        # also ignore the shadow repo itself and .git
        self._ignores: set[str] = {
            ".git",
            AGENT_DATA_DIR,
            os.path.basename(self._repodir),
        }
        self._ignore_mgr = IgnoreFilterManager(self._workdir, global_filters, False)

        # ── index (staging area on disk) ────────────────
        self._index_path = os.path.join(self._repodir, "index")
        self._idx = Index(self._index_path)

    # ── public API ───────────────────────────────────────

    def snapshot(self, session_id: str, message: str) -> str:
        """Take a snapshot of the current workspace.

        Returns the full 40-char commit sha hex string.
        """
        live: set[bytes] = set()

        for root, dirs, files in os.walk(self._workdir):
            # prune ignored directories
            dirs[:] = [
                d
                for d in dirs
                if d not in self._ignores
                and not self._ignore_mgr.is_ignored(
                    os.path.relpath(os.path.join(root, d), self._workdir) + "/"
                )
            ]
            for fn in files:
                full = os.path.join(root, fn)
                rel = os.path.relpath(full, self._workdir).encode()

                if self._ignore_mgr.is_ignored(rel.decode()):
                    continue
                live.add(rel)

                content = open(full, "rb").read()

                # skip unchanged files
                try:
                    if self._idx[rel].sha == Blob.from_string(content).id:
                        continue
                except KeyError:
                    pass

                blob = Blob.from_string(content)
                self._repo.object_store.add_object(blob)
                self._idx[rel] = IndexEntry(
                    0, 0, 0, 0, 0o100644, 0, 0, len(content), blob.id
                )

        # remove deleted files from index
        deleted = [p for p in self._idx if p not in live]
        for p in deleted:
            del self._idx[p]

        tree_id = self._idx.commit(self._repo.object_store)
        self._idx.write()

        # ── build commit ────────────────────────────────
        msg = message

        c = Commit()
        c.tree = tree_id
        c.author = c.committer = b"Shadow <s@vcs>"
        c.author_time = c.commit_time = int(time.time())
        c.author_timezone = c.commit_timezone = 0
        c.message = msg.encode()

        try:
            parent = self._repo.refs.read_ref(self._branch_ref(session_id))
        except KeyError:
            parent = None
        if parent:
            c.parents = [parent]

        self._repo.object_store.add_object(c)
        self._repo.refs[self._branch_ref(session_id)] = c.id

        return c.id.decode()

    def restore(self, commit_sha: str) -> None:
        """Checkout a commit's tree into the workspace, overwriting files."""

        c = self._get_commit(commit_sha)
        tree = self._repo.object_store[c.tree]

        # Recursively collect all file entries
        entries = _walk_tree(self._repo.object_store, c.tree)

        # Ensure all directories exist
        dirs: set[str] = set()
        for name, _, _ in entries:
            parent = os.path.dirname(name.decode())
            if parent:
                dirs.add(parent)
        for d in sorted(dirs):
            _ensure_dir(os.path.join(self._workdir, d))

        # Track file names for cleanup
        tracked: set[bytes] = {name for name, _, _ in entries}

        # Write all files
        for name, mode, sha in entries:
            target = os.path.join(self._workdir, name.decode())
            _ensure_dir(os.path.dirname(target))
            blob = self._repo.object_store[sha]
            with open(target, "wb") as f:
                f.write(blob.data)

        # Remove workspace files that are not in the target tree.
        # Walk the workdir and delete any non-ignored file not in tracked.
        for root, dirs, files in os.walk(self._workdir, topdown=True):
            dirs[:] = [
                d
                for d in dirs
                if d not in self._ignores
                and not self._ignore_mgr.is_ignored(
                    os.path.relpath(os.path.join(root, d), self._workdir) + "/"
                )
            ]
            for fn in files:
                full = os.path.join(root, fn)
                rel = os.path.relpath(full, self._workdir).encode()
                if self._ignore_mgr.is_ignored(rel.decode()):
                    continue
                if rel not in tracked:
                    try:
                        os.remove(full)
                    except OSError:
                        pass

        # Remove empty directories (bottom-up)
        for root, dirs, _ in os.walk(self._workdir, topdown=False):
            for d in dirs:
                if d in self._ignores:
                    continue
                full = os.path.join(root, d)
                rel = os.path.relpath(full, self._workdir).encode()
                if self._ignore_mgr.is_ignored(rel.decode() + "/"):
                    continue
                try:
                    os.rmdir(full)  # only removes if empty
                except OSError:
                    pass

        # Rebuild index from the restored tree
        self._idx = Index(self._index_path)
        for name, mode, sha in entries:
            blob = self._repo.object_store[sha]
            self._idx[name] = IndexEntry(0, 0, 0, 0, mode, 0, 0, len(blob.data), sha)
        self._idx.write()

    def list_commits(self, session_id: str) -> list[dict[str, Any]]:
        """Walk parent chain from HEAD, return commit metadata list."""
        result: list[dict[str, Any]] = []
        try:
            head = self._repo.refs.read_ref(self._branch_ref(session_id))
        except KeyError:
            return result
        if head is None:
            return result

        for entry in Walker(self._repo.object_store, head):
            c = entry.commit
            sha = c.id.decode()
            result.append(
                {
                    "sha": sha,
                    "short_sha": sha[:7],
                    "message": c.message.decode().splitlines()[0],
                    "author_time": c.author_time,
                }
            )
        return result

    def get_commit(self, commit_sha: str) -> dict[str, Any]:
        """Get full metadata for a commit."""
        c = self._get_commit(commit_sha)
        sha = c.id.decode()
        entries = _walk_tree(self._repo.object_store, c.tree)
        return {
            "sha": sha,
            "short_sha": sha[:7],
            "message": c.message.decode().splitlines()[0],
            "author_time": c.author_time,
            "files": sorted(name.decode() for name, _, _ in entries),
        }

    def diff(self, sha1: str, sha2: str) -> str:
        """Unified diff between two commits."""
        c1 = self._get_commit(sha1)
        c2 = self._get_commit(sha2)
        parts: list[str] = []

        for change in tree_changes(self._repo.object_store, c1.tree, c2.tree):
            old, new = change.old, change.new
            if old and new and old.sha == new.sha:
                continue
            buf = BytesIO()
            write_object_diff(
                buf,
                self._repo.object_store,
                (old.path, old.mode, old.sha) if old else (None, None, None),
                (new.path, new.mode, new.sha) if new else (None, None, None),
            )
            parts.append(buf.getvalue().decode())
        return "\n".join(parts)

    def soft_reset(self, session_id: str, commit_sha: str) -> str:
        """Reset HEAD to the parent of commit_sha, keeping the working tree unchanged.

        Similar to ``git reset --soft HEAD~1`` — the commit is discarded but
        all file changes remain in the workspace.

        Returns the new HEAD sha (the parent commit).
        """
        c = self._get_commit(commit_sha)
        if not c.parents:
            raise ValueError("Commit has no parent; cannot soft reset")
        parent_sha_bytes = c.parents[0]
        parent_sha = parent_sha_bytes.decode()

        # Move HEAD to parent
        self._repo.refs[self._branch_ref(session_id)] = parent_sha_bytes

        return parent_sha

    def set_head(self, session_id: str, commit_sha: str) -> None:
        """Point HEAD directly to commit_sha, discarding any later commits."""
        self._get_commit(commit_sha)
        self._repo.refs[self._branch_ref(session_id)] = commit_sha.encode()

    def delete_branch(self, session_id: str) -> None:
        branch = self._branch_ref(session_id)
        try:
            head = self._repo.refs.read_ref(branch)
        except KeyError:
            return
        if head is None:
            return
        try:
            del self._repo.refs[branch]
        except KeyError:
            pass

    # ── internal ─────────────────────────────────────────

    def _get_commit(self, sha: str) -> Commit:
        obj = self._repo.get_object(sha.encode())
        if not isinstance(obj, Commit):
            raise KeyError(f"Not a commit: {sha}")
        return obj
