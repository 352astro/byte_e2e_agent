"""
Comprehensive unit tests for ShadowRepo (链路 10).

Tests cover construction, snapshot, list_commits, restore, get_commit,
set_head, delete_branch, and integration flow.
"""

import os
import tempfile
from pathlib import Path

import pytest

from agent.shadow_repo import ShadowRepo

# ── helpers ──────────────────────────────────────────────────────────


def make_file(workdir: str, relpath: str, content: str) -> str:
    """Create a file under workdir, creating parent dirs as needed. Returns the full path."""
    full = os.path.join(workdir, relpath)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w") as f:
        f.write(content)
    return full


def read_file(workdir: str, relpath: str) -> str:
    """Read a file under workdir."""
    with open(os.path.join(workdir, relpath)) as f:
        return f.read()


def file_exists(workdir: str, relpath: str) -> bool:
    """Check if a file exists under workdir."""
    return os.path.isfile(os.path.join(workdir, relpath))


# ── fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def workdir():
    """Create a temporary workspace directory."""
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def shadow(workdir: str) -> ShadowRepo:
    """Create a ShadowRepo with repodir under workdir's .byte_agent/.shadow-vcs."""
    repodir = os.path.join(workdir, ".byte_agent", ".shadow-vcs")
    return ShadowRepo(workdir=workdir, repodir=repodir)


@pytest.fixture
def branch() -> str:
    return "test-session-42"


# ── Construction ─────────────────────────────────────────────────────


class TestConstruction:
    def test_creates_repo_directory(self, workdir: str):
        """Constructor creates repo directory."""
        repodir = os.path.join(workdir, ".byte_agent", ".shadow-vcs")
        ShadowRepo(workdir=workdir, repodir=repodir)
        assert os.path.isdir(repodir)

    def test_works_with_string_workspace(self):
        """Works with string workspace."""
        with tempfile.TemporaryDirectory() as d:
            repodir = os.path.join(d, ".byte_agent", ".shadow-vcs")
            sr = ShadowRepo(workdir=d, repodir=repodir)
            assert os.path.isdir(sr._repodir)

    def test_works_with_path_workspace(self):
        """Works with Path workspace (converted to string via str())."""
        with tempfile.TemporaryDirectory() as d:
            repodir = os.path.join(str(Path(d)), ".byte_agent", ".shadow-vcs")
            sr = ShadowRepo(workdir=str(Path(d)), repodir=repodir)
            assert os.path.isdir(sr._repodir)

    def test_repodir_under_agent_dir_shadow_vcs(self, shadow: ShadowRepo, workdir: str):
        """repo_dir is under .byte_agent/.shadow-vcs."""
        expected = os.path.join(workdir, ".byte_agent", ".shadow-vcs")
        assert shadow._repodir == os.path.abspath(expected)


# ── snapshot ──────────────────────────────────────────────────────────


class TestSnapshot:
    def test_returns_commit_sha_string(self, shadow: ShadowRepo, branch: str):
        """Takes a branch name and message; returns a commit SHA string."""
        sha = shadow.snapshot(branch, "initial commit")
        assert isinstance(sha, str)
        assert len(sha) == 40
        assert all(c in "0123456789abcdef" for c in sha)

    def test_creates_a_commit_in_the_repo(self, shadow: ShadowRepo, branch: str):
        """Creates a commit in the shadow repo."""
        sha = shadow.snapshot(branch, "initial")
        # The commit should be retrievable
        commit_info = shadow.get_commit(sha)
        assert commit_info["sha"] == sha
        assert commit_info["message"] == "initial"
        assert "message_id" not in commit_info

    def test_works_with_files_in_workspace(self, shadow: ShadowRepo, workdir: str, branch: str):
        """Works when there are files in the workspace."""
        make_file(workdir, "hello.txt", "Hello, world!")
        make_file(workdir, "src/main.py", "print('hi')")

        sha = shadow.snapshot(branch, "add files")

        commit_info = shadow.get_commit(sha)
        assert sorted(commit_info["files"]) == ["hello.txt", "src/main.py"]

    def test_works_with_empty_workspace(self, shadow: ShadowRepo, branch: str):
        """Works with empty workspace (no files)."""
        sha = shadow.snapshot(branch, "empty state")
        commit_info = shadow.get_commit(sha)
        assert commit_info["files"] == []

    def test_multiple_snapshots_create_chain(self, shadow: ShadowRepo, workdir: str, branch: str):
        """Multiple snapshots form a parent chain on the same branch."""
        sha1 = shadow.snapshot(branch, "first")
        make_file(workdir, "a.txt", "A")
        sha2 = shadow.snapshot(branch, "second")
        make_file(workdir, "b.txt", "B")
        sha3 = shadow.snapshot(branch, "third")

        commits = shadow.list_commits(branch)
        shas = [c["sha"] for c in commits]
        assert shas[0] == sha3  # newest first
        assert shas[1] == sha2
        assert shas[2] == sha1


# ── list_commits ──────────────────────────────────────────────────────


class TestListCommits:
    def test_returns_list_of_commit_dicts(self, shadow: ShadowRepo, branch: str):
        """Returns list of commit dicts with sha, message, author_time."""
        sha = shadow.snapshot(branch, "my message")
        commits = shadow.list_commits(branch)
        assert isinstance(commits, list)
        assert len(commits) == 1
        c = commits[0]
        assert c["sha"] == sha
        assert c["short_sha"] == sha[:7]
        assert c["message"] == "my message"
        assert "author_time" in c
        assert "message_id" not in c

    def test_empty_list_for_new_branch(self, shadow: ShadowRepo):
        """Empty list for a branch that has no commits."""
        commits = shadow.list_commits("nonexistent-branch")
        assert commits == []

    def test_returns_commits_in_chronological_order(
        self, shadow: ShadowRepo, workdir: str, branch: str
    ):
        """Returns commits newest-first (reverse chronological)."""
        shadow.snapshot(branch, "oldest")
        make_file(workdir, "x.txt", "x")
        shadow.snapshot(branch, "middle")
        make_file(workdir, "y.txt", "y")
        shadow.snapshot(branch, "newest")

        commits = shadow.list_commits(branch)
        messages = [c["message"] for c in commits]
        assert messages == ["newest", "middle", "oldest"]


# ── restore ───────────────────────────────────────────────────────────


class TestRestore:
    def test_restores_workspace_to_previous_commit(
        self, shadow: ShadowRepo, workdir: str, branch: str
    ):
        """Restores workspace to a previous commit SHA."""
        make_file(workdir, "a.txt", "version A")
        sha_a = shadow.snapshot(branch, "state A")

        make_file(workdir, "b.txt", "version B")
        shadow.snapshot(branch, "state B")

        # Restore to state A
        shadow.restore(sha_a)

        assert file_exists(workdir, "a.txt")
        assert read_file(workdir, "a.txt") == "version A"
        assert not file_exists(workdir, "b.txt")

    def test_raises_keyerror_for_unknown_sha(self, shadow: ShadowRepo):
        """Raises KeyError for unknown SHA."""
        with pytest.raises(KeyError):
            shadow.restore("0" * 40)

    def test_after_restore_files_match_committed_state(
        self, shadow: ShadowRepo, workdir: str, branch: str
    ):
        """After restore, workspace files match the committed state exactly."""
        make_file(workdir, "f1.txt", "one")
        make_file(workdir, "sub/f2.txt", "two")
        sha1 = shadow.snapshot(branch, "two files")

        # Modify and add a file
        make_file(workdir, "f1.txt", "one-modified")
        make_file(workdir, "f3.txt", "three")
        shadow.snapshot(branch, "modified")

        # Restore to sha1
        shadow.restore(sha1)

        assert read_file(workdir, "f1.txt") == "one"
        assert read_file(workdir, "sub/f2.txt") == "two"
        assert not file_exists(workdir, "f3.txt")

    def test_restore_removes_empty_directories(self, shadow: ShadowRepo, workdir: str, branch: str):
        """After restore, empty directories from later commits are cleaned up."""
        make_file(workdir, "keep.txt", "keep")
        sha_keep = shadow.snapshot(branch, "keep")

        make_file(workdir, "extra_dir/extra_file.txt", "extra")
        shadow.snapshot(branch, "with extra dir")

        shadow.restore(sha_keep)
        assert not os.path.isdir(os.path.join(workdir, "extra_dir"))


# ── get_commit ────────────────────────────────────────────────────────


class TestGetCommit:
    def test_returns_commit_metadata(self, shadow: ShadowRepo, workdir: str, branch: str):
        """Returns commit metadata for a given SHA."""
        make_file(workdir, "data.txt", "payload")
        sha = shadow.snapshot(branch, "save data")

        info = shadow.get_commit(sha)
        assert info["sha"] == sha
        assert info["short_sha"] == sha[:7]
        assert info["message"] == "save data"
        assert "message_id" not in info
        assert "author_time" in info
        assert "files" in info
        assert "data.txt" in info["files"]

    def test_raises_keyerror_for_unknown_sha(self, shadow: ShadowRepo):
        """Raises KeyError for unknown SHA."""
        with pytest.raises(KeyError):
            shadow.get_commit("0" * 40)

    def test_raises_keyerror_for_non_commit_object(
        self, shadow: ShadowRepo, workdir: str, branch: str
    ):
        """Raises KeyError when SHA points to a non-commit object."""
        # Create a file that produces a blob, then try to use its SHA
        make_file(workdir, "blob_test.txt", "blob content")
        sha = shadow.snapshot(branch, "commit with blob")

        # Get the tree sha from the commit and use that — it's not a commit
        commit = shadow._repo.get_object(sha.encode())
        tree_sha = commit.tree.decode()

        with pytest.raises(KeyError):
            shadow.get_commit(tree_sha)


# ── set_head ──────────────────────────────────────────────────────────


class TestSetHead:
    def test_moves_head_to_specific_commit(self, shadow: ShadowRepo, workdir: str, branch: str):
        """Moves HEAD to a specific commit, discarding later commits."""
        make_file(workdir, "first.txt", "first")
        sha1 = shadow.snapshot(branch, "commit 1")

        make_file(workdir, "second.txt", "second")
        sha2 = shadow.snapshot(branch, "commit 2")

        make_file(workdir, "third.txt", "third")
        sha3 = shadow.snapshot(branch, "commit 3")

        # Move HEAD back to sha1
        shadow.set_head(branch, sha1)

        commits = shadow.list_commits(branch)
        shas = [c["sha"] for c in commits]
        assert shas == [sha1]
        assert sha2 not in shas
        assert sha3 not in shas

    def test_set_head_raises_keyerror_for_unknown_sha(self, shadow: ShadowRepo, branch: str):
        """Raises KeyError when setting HEAD to unknown SHA."""
        with pytest.raises(KeyError):
            shadow.set_head(branch, "0" * 40)


# ── delete_branch ─────────────────────────────────────────────────────


class TestDeleteBranch:
    def test_removes_branch_reference(self, shadow: ShadowRepo, workdir: str, branch: str):
        """Removes a branch reference."""
        make_file(workdir, "keep.txt", "data")
        shadow.snapshot(branch, "on branch")

        # Branch should have commits before deletion
        assert len(shadow.list_commits(branch)) > 0

        shadow.delete_branch(branch)

        # After deletion, listing commits returns empty
        assert shadow.list_commits(branch) == []

    def test_does_not_raise_for_nonexistent_branch(self, shadow: ShadowRepo):
        """Does not raise for nonexistent branch."""
        # Should complete without exception
        shadow.delete_branch("no-such-branch")


# ── Integration flow ──────────────────────────────────────────────────


class TestIntegration:
    def test_snapshot_list_restore_verify(self, shadow: ShadowRepo, workdir: str, branch: str):
        """Integration: snapshot → list_commits → restore → verify files."""
        # Step 1: Initial snapshot on empty workspace
        sha_empty = shadow.snapshot(branch, "empty workspace")
        assert len(shadow.list_commits(branch)) == 1

        # Step 2: Add files and snapshot
        make_file(workdir, "README.md", "# Project")
        make_file(workdir, "src/app.py", "print('app')")
        make_file(workdir, "tests/test_app.py", "assert True")
        sha_with_files = shadow.snapshot(branch, "add project files")

        commits = shadow.list_commits(branch)
        assert len(commits) == 2
        assert commits[0]["sha"] == sha_with_files
        assert commits[1]["sha"] == sha_empty

        # Step 3: Modify a file and add another
        make_file(workdir, "src/app.py", "print('updated app')")
        make_file(workdir, "config.json", '{"debug": true}')
        shadow.snapshot(branch, "update app, add config")

        assert len(shadow.list_commits(branch)) == 3

        # Step 4: Restore to sha_with_files
        shadow.restore(sha_with_files)

        assert read_file(workdir, "README.md") == "# Project"
        assert read_file(workdir, "src/app.py") == "print('app')"
        assert read_file(workdir, "tests/test_app.py") == "assert True"
        assert not file_exists(workdir, "config.json")

        # Step 5: Restore all the way back to empty
        shadow.restore(sha_empty)
        assert not file_exists(workdir, "README.md")
        assert not file_exists(workdir, "src/app.py")
        assert not file_exists(workdir, "tests/test_app.py")

    def test_cross_branch_isolation(self, shadow: ShadowRepo, workdir: str):
        """Different branches have independent commit histories."""
        branch_a = "session-A"
        branch_b = "session-B"

        make_file(workdir, "a.txt", "A")
        sha_a = shadow.snapshot(branch_a, "A commit")

        # Clear workspace and create file for branch B
        shadow.restore(sha_a)  # first restore to something we can clean from
        # Actually, delete all files manually to simulate a fresh start
        for f in os.listdir(workdir):
            fp = os.path.join(workdir, f)
            if os.path.isfile(fp):
                os.remove(fp)

        make_file(workdir, "b.txt", "B")
        sha_b = shadow.snapshot(branch_b, "B commit")

        # Branch A should have its own commit
        commits_a = shadow.list_commits(branch_a)
        assert len(commits_a) == 1
        assert commits_a[0]["sha"] == sha_a

        # Branch B should have its own commit
        commits_b = shadow.list_commits(branch_b)
        assert len(commits_b) == 1
        assert commits_b[0]["sha"] == sha_b

        # Restoring branch A's commit brings back a.txt
        shadow.restore(sha_a)
        assert file_exists(workdir, "a.txt")
        assert not file_exists(workdir, "b.txt")

        # Restoring branch B's commit brings back b.txt
        shadow.restore(sha_b)
        assert file_exists(workdir, "b.txt")
        assert not file_exists(workdir, "a.txt")

    def test_commits_do_not_expose_message_mapping(
        self, shadow: ShadowRepo, workdir: str, branch: str
    ):
        """Shadow commits are independent from Message identity."""
        make_file(workdir, "t1.txt", "one")
        sha = shadow.snapshot(branch, "first")

        commit = shadow.get_commit(sha)
        listed = shadow.list_commits(branch)[0]

        assert "message_id" not in commit
        assert "message_id" not in listed
        assert not hasattr(shadow, "commit_for_message")
        assert not hasattr(shadow, "commit_for_transcript")
