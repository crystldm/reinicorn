"""Tests for reins.validation boundary checks."""

from __future__ import annotations

import pytest

from reinicorn.validation import (
    is_valid_scope_name,
    validate_git_url,
    validate_hook_name,
    validate_safe_name,
)


class TestValidateSafeName:
    """SEC-04, SEC-05: name validation rejects path traversal and shell metacharacters."""

    def test_simple_name(self):
        assert validate_safe_name("my-task") == "my-task"

    def test_name_with_dots(self):
        assert validate_safe_name("v1.2.3") == "v1.2.3"

    def test_name_with_underscores(self):
        assert validate_safe_name("my_extension") == "my_extension"

    def test_rejects_path_traversal(self):
        with pytest.raises(ValueError, match="path traversal"):
            validate_safe_name("../../etc/passwd")

    def test_rejects_dotdot(self):
        with pytest.raises(ValueError, match="path traversal"):
            validate_safe_name("..")

    def test_rejects_slash(self):
        with pytest.raises(ValueError, match="path traversal"):
            validate_safe_name("foo/bar")

    def test_rejects_backslash(self):
        with pytest.raises(ValueError, match="path traversal"):
            validate_safe_name("foo\\bar")

    def test_rejects_null_byte(self):
        with pytest.raises(ValueError, match="path traversal"):
            validate_safe_name("foo\x00bar")

    def test_rejects_empty(self):
        with pytest.raises(ValueError, match="path traversal"):
            validate_safe_name("")

    def test_rejects_dot_prefix(self):
        with pytest.raises(ValueError, match="path traversal"):
            validate_safe_name(".hidden")

    def test_rejects_shell_metacharacters(self):
        for bad in ["foo;bar", "foo|bar", "foo$(cmd)", "foo`cmd`", "foo&bar"]:
            with pytest.raises(ValueError, match="path traversal"):
                validate_safe_name(bad)


class TestValidateHookName:
    """SEC-03: hook name validation rejects arbitrary filenames."""

    def test_valid_hook(self):
        assert validate_hook_name("post-checkout") == "post-checkout"

    def test_valid_pre_push(self):
        assert validate_hook_name("pre-push") == "pre-push"

    def test_rejects_traversal(self):
        with pytest.raises(ValueError, match="not a recognized git hook"):
            validate_hook_name("../../.profile")

    def test_rejects_arbitrary_name(self):
        with pytest.raises(ValueError, match="not a recognized git hook"):
            validate_hook_name("run-my-payload")

    def test_rejects_empty(self):
        with pytest.raises(ValueError, match="not a recognized git hook"):
            validate_hook_name("")


class TestIsValidScopeName:
    """A KB scope becomes a directory name under kb/ — reject unsafe slugs."""

    def test_accepts_simple(self):
        assert is_valid_scope_name("my-project")

    def test_accepts_dotted(self):
        assert is_valid_scope_name("v1.2.3")

    def test_rejects_empty(self):
        assert not is_valid_scope_name("")

    def test_rejects_traversal(self):
        assert not is_valid_scope_name("../escape")

    def test_rejects_dotdot(self):
        assert not is_valid_scope_name("..")

    def test_rejects_leading_dot(self):
        assert not is_valid_scope_name(".hidden")

    def test_rejects_leading_underscore(self):
        assert not is_valid_scope_name("_reserved")

    def test_rejects_option_like(self):
        assert not is_valid_scope_name("-rf")

    def test_rejects_slash(self):
        assert not is_valid_scope_name("a/b")

    def test_rejects_whitespace(self):
        assert not is_valid_scope_name("a b")


class TestValidateGitUrl:
    """Only hand git transports that cannot run commands or inject options."""

    def test_accepts_https(self):
        assert validate_git_url("https://github.com/o/r.git") is None

    def test_accepts_scp_like(self):
        assert validate_git_url("git@github.com:o/r.git") is None

    def test_accepts_ssh_scheme(self):
        assert validate_git_url("ssh://git@host/o/r.git") is None

    def test_accepts_local_absolute(self):
        assert validate_git_url("/srv/git/kb.git") is None

    def test_rejects_empty(self):
        assert validate_git_url("") is not None

    def test_rejects_transport_helper(self):
        # ext:: can run arbitrary commands.
        assert validate_git_url("ext::sh -c whoami") is not None

    def test_rejects_option_like(self):
        assert validate_git_url("--upload-pack=payload") is not None

    def test_rejects_git_protocol(self):
        assert validate_git_url("git://host/o/r.git") is not None

    def test_rejects_control_characters(self):
        assert validate_git_url("https://host/r\n.git") is not None

    def test_rejects_surrounding_whitespace(self):
        assert validate_git_url("  https://host/r.git ") is not None
