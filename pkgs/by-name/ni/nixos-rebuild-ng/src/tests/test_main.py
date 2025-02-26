import logging
import textwrap
from pathlib import Path
from subprocess import PIPE, CompletedProcess
from typing import Any
from unittest.mock import ANY, call, patch

import pytest

import nixos_rebuild as nr

from .helpers import get_qualified_name

DEFAULT_RUN_KWARGS = {
    "env": ANY,
    "input": None,
    "text": True,
    "errors": "surrogateescape",
}


def test_parse_args() -> None:
    with pytest.raises(SystemExit) as e:
        nr.parse_args(["nixos-rebuild", "unknown-action"])
    assert e.value.code == 2

    with pytest.raises(SystemExit) as e:
        nr.parse_args(["nixos-rebuild", "test", "--flake", "--file", "abc"])
    assert e.value.code == 2

    with pytest.raises(SystemExit) as e:
        nr.parse_args(["nixos-rebuild", "edit", "--attr", "attr"])
    assert e.value.code == 2

    r1, g1 = nr.parse_args(
        [
            "nixos-rebuild",
            "switch",
            "--install-grub",
            "--flake",
            "/etc/nixos",
            "--option",
            "foo",
            "bar",
        ]
    )
    assert nr.logger.level == logging.INFO
    assert r1.flake == "/etc/nixos"
    assert r1.install_bootloader is True
    assert r1.install_grub is True
    assert r1.profile_name == "system"
    assert r1.action == "switch"
    assert r1.option == ["foo", "bar"]
    assert g1["common_flags"].option == ["foo", "bar"]

    r2, g2 = nr.parse_args(
        [
            "nixos-rebuild",
            "dry-run",
            "--flake",
            "--no-flake",
            "-f",
            "foo",
            "--attr",
            "bar",
            "-vvv",
        ]
    )
    assert nr.logger.level == logging.DEBUG
    assert r2.v == 3
    assert r2.flake is False
    assert r2.action == "dry-build"
    assert r2.file == "foo"
    assert r2.attr == "bar"
    assert g2["common_flags"].v == 3


@patch.dict(nr.process.os.environ, {}, clear=True)
@patch(get_qualified_name(nr.process.subprocess.run), autospec=True)
def test_execute_nix_boot(mock_run: Any, tmp_path: Path) -> None:
    nixpkgs_path = tmp_path / "nixpkgs"
    nixpkgs_path.mkdir()
    config_path = tmp_path / "test"
    config_path.touch()

    def run_side_effect(args: list[str], **kwargs: Any) -> CompletedProcess[str]:
        if args[0] == "nix-instantiate":
            return CompletedProcess([], 0, str(nixpkgs_path))
        elif args[0] == "git" and "rev-parse" in args:
            return CompletedProcess([], 0, "nixpkgs-rev")
        elif args[0] == "nix-build":
            return CompletedProcess([], 0, str(config_path))
        else:
            return CompletedProcess([], 0)

    mock_run.side_effect = run_side_effect

    nr.execute(["nixos-rebuild", "boot", "--no-flake", "-vvv", "--fast"])

    assert mock_run.call_count == 6
    mock_run.assert_has_calls(
        [
            call(
                ["nix-instantiate", "--find-file", "nixpkgs", "-vvv"],
                stdout=PIPE,
                check=False,
                **DEFAULT_RUN_KWARGS,
            ),
            call(
                ["git", "-C", nixpkgs_path, "rev-parse", "--short", "HEAD"],
                check=False,
                capture_output=True,
                **DEFAULT_RUN_KWARGS,
            ),
            call(
                ["git", "-C", nixpkgs_path, "diff", "--quiet"],
                check=False,
                **DEFAULT_RUN_KWARGS,
            ),
            call(
                [
                    "nix-build",
                    "<nixpkgs/nixos>",
                    "--attr",
                    "config.system.build.toplevel",
                    "-vvv",
                    "--no-out-link",
                ],
                check=True,
                stdout=PIPE,
                **DEFAULT_RUN_KWARGS,
            ),
            call(
                [
                    "nix-env",
                    "-p",
                    Path("/nix/var/nix/profiles/system"),
                    "--set",
                    config_path,
                ],
                check=True,
                **DEFAULT_RUN_KWARGS,
            ),
            call(
                [config_path / "bin/switch-to-configuration", "boot"],
                check=True,
                **(DEFAULT_RUN_KWARGS | {"env": {"NIXOS_INSTALL_BOOTLOADER": "0"}}),
            ),
        ]
    )


@patch.dict(nr.process.os.environ, {}, clear=True)
@patch(get_qualified_name(nr.process.subprocess.run), autospec=True)
def test_execute_nix_build_vm(mock_run: Any, tmp_path: Path) -> None:
    config_path = tmp_path / "test"
    config_path.touch()

    def run_side_effect(args: list[str], **kwargs: Any) -> CompletedProcess[str]:
        if args[0] == "nix-build":
            return CompletedProcess([], 0, str(config_path))
        else:
            return CompletedProcess([], 0)

    mock_run.side_effect = run_side_effect

    nr.execute(
        [
            "nixos-rebuild",
            "build-vm",
            "--no-flake",
            "-I",
            "nixos-config=./configuration.nix",
            "-I",
            "nixpkgs=$HOME/.nix-defexpr/channels/pinned_nixpkgs",
            "--fast",
        ]
    )

    assert mock_run.call_count == 1
    mock_run.assert_has_calls(
        [
            call(
                [
                    "nix-build",
                    "<nixpkgs/nixos>",
                    "--attr",
                    "config.system.build.vm",
                    "--include",
                    "nixos-config=./configuration.nix",
                    "--include",
                    "nixpkgs=$HOME/.nix-defexpr/channels/pinned_nixpkgs",
                ],
                check=True,
                stdout=PIPE,
                **DEFAULT_RUN_KWARGS,
            )
        ]
    )


@patch.dict(nr.process.os.environ, {}, clear=True)
@patch(get_qualified_name(nr.process.subprocess.run), autospec=True)
def test_execute_nix_build_image_flake(mock_run: Any, tmp_path: Path) -> None:
    config_path = tmp_path / "test"
    config_path.touch()

    def run_side_effect(args: list[str], **kwargs: Any) -> CompletedProcess[str]:
        if args[0] == "nix" and "eval" in args:
            return CompletedProcess(
                [],
                0,
                """
                {
                  "azure": "nixos-image-azure-25.05.20250102.6df2492-x86_64-linux.vhd",
                  "vmware": "nixos-image-vmware-25.05.20250102.6df2492-x86_64-linux.vmdk"
                }
                """,
            )
        elif args[0] == "nix":
            return CompletedProcess([], 0, str(config_path))
        else:
            return CompletedProcess([], 0)

    mock_run.side_effect = run_side_effect

    nr.execute(
        [
            "nixos-rebuild",
            "build-image",
            "--image-variant",
            "azure",
            "--flake",
            "/path/to/config#hostname",
        ]
    )

    assert mock_run.call_count == 2
    mock_run.assert_has_calls(
        [
            call(
                [
                    "nix",
                    "eval",
                    "--json",
                    "/path/to/config#nixosConfigurations.hostname.config.system.build.images",
                    "--apply",
                    "builtins.mapAttrs (n: v: v.passthru.filePath)",
                ],
                check=True,
                stdout=PIPE,
                **DEFAULT_RUN_KWARGS,
            ),
            call(
                [
                    "nix",
                    "--extra-experimental-features",
                    "nix-command flakes",
                    "build",
                    "--print-out-paths",
                    "/path/to/config#nixosConfigurations.hostname.config.system.build.images.azure",
                ],
                check=True,
                stdout=PIPE,
                **DEFAULT_RUN_KWARGS,
            ),
        ]
    )


@patch.dict(nr.process.os.environ, {}, clear=True)
@patch(get_qualified_name(nr.process.subprocess.run), autospec=True)
def test_execute_nix_switch_flake(mock_run: Any, tmp_path: Path) -> None:
    config_path = tmp_path / "test"
    config_path.touch()

    def run_side_effect(args: list[str], **kwargs: Any) -> CompletedProcess[str]:
        if args[0] == "nix":
            return CompletedProcess([], 0, str(config_path))
        else:
            return CompletedProcess([], 0)

    mock_run.side_effect = run_side_effect

    nr.execute(
        [
            "nixos-rebuild",
            "switch",
            "--flake",
            "/path/to/config#hostname",
            "--install-bootloader",
            "--sudo",
            "--verbose",
            "--fast",
        ]
    )

    assert mock_run.call_count == 3
    mock_run.assert_has_calls(
        [
            call(
                [
                    "nix",
                    "--extra-experimental-features",
                    "nix-command flakes",
                    "build",
                    "--print-out-paths",
                    "/path/to/config#nixosConfigurations.hostname.config.system.build.toplevel",
                    "-v",
                    "--no-link",
                ],
                check=True,
                stdout=PIPE,
                **DEFAULT_RUN_KWARGS,
            ),
            call(
                [
                    "sudo",
                    "nix-env",
                    "-p",
                    Path("/nix/var/nix/profiles/system"),
                    "--set",
                    config_path,
                ],
                check=True,
                **DEFAULT_RUN_KWARGS,
            ),
            call(
                ["sudo", config_path / "bin/switch-to-configuration", "switch"],
                check=True,
                **(DEFAULT_RUN_KWARGS | {"env": {"NIXOS_INSTALL_BOOTLOADER": "1"}}),
            ),
        ]
    )


@patch.dict(nr.process.os.environ, {}, clear=True)
@patch(get_qualified_name(nr.process.subprocess.run), autospec=True)
@patch(get_qualified_name(nr.cleanup_ssh, nr), autospec=True)
def test_execute_nix_switch_flake_target_host(
    mock_cleanup_ssh: Any,
    mock_run: Any,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "test"
    config_path.touch()

    def run_side_effect(args: list[str], **kwargs: Any) -> CompletedProcess[str]:
        if args[0] == "nix":
            return CompletedProcess([], 0, str(config_path))
        else:
            return CompletedProcess([], 0)

    mock_run.side_effect = run_side_effect

    nr.execute(
        [
            "nixos-rebuild",
            "switch",
            "--flake",
            "/path/to/config#hostname",
            "--use-remote-sudo",
            "--target-host",
            "user@localhost",
            "--fast",
        ]
    )

    assert mock_run.call_count == 4
    mock_run.assert_has_calls(
        [
            call(
                [
                    "nix",
                    "--extra-experimental-features",
                    "nix-command flakes",
                    "build",
                    "--print-out-paths",
                    "/path/to/config#nixosConfigurations.hostname.config.system.build.toplevel",
                    "--no-link",
                ],
                check=True,
                stdout=PIPE,
                **DEFAULT_RUN_KWARGS,
            ),
            call(
                ["nix-copy-closure", "--to", "user@localhost", config_path],
                check=True,
                **DEFAULT_RUN_KWARGS,
            ),
            call(
                [
                    "ssh",
                    *nr.process.SSH_DEFAULT_OPTS,
                    "user@localhost",
                    "--",
                    "sudo",
                    "nix-env",
                    "-p",
                    "/nix/var/nix/profiles/system",
                    "--set",
                    str(config_path),
                ],
                check=True,
                **DEFAULT_RUN_KWARGS,
            ),
            call(
                [
                    "ssh",
                    *nr.process.SSH_DEFAULT_OPTS,
                    "user@localhost",
                    "--",
                    "sudo",
                    "env",
                    "NIXOS_INSTALL_BOOTLOADER=0",
                    f"{config_path / 'bin/switch-to-configuration'}",
                    "switch",
                ],
                check=True,
                **DEFAULT_RUN_KWARGS,
            ),
        ]
    )


@patch.dict(nr.process.os.environ, {}, clear=True)
@patch(get_qualified_name(nr.process.subprocess.run), autospec=True)
@patch(get_qualified_name(nr.cleanup_ssh, nr), autospec=True)
def test_execute_nix_switch_flake_build_host(
    mock_cleanup_ssh: Any,
    mock_run: Any,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "test"
    config_path.touch()

    def run_side_effect(args: list[str], **kwargs: Any) -> CompletedProcess[str]:
        if args[0] == "nix" and "eval" in args:
            return CompletedProcess([], 0, str(config_path))
        if args[0] == "ssh" and "nix" in args:
            return CompletedProcess([], 0, str(config_path))
        else:
            return CompletedProcess([], 0)

    mock_run.side_effect = run_side_effect

    nr.execute(
        [
            "nixos-rebuild",
            "switch",
            "--flake",
            "/path/to/config#hostname",
            "--build-host",
            "user@localhost",
            "--fast",
        ]
    )

    assert mock_run.call_count == 6
    mock_run.assert_has_calls(
        [
            call(
                [
                    "nix",
                    "--extra-experimental-features",
                    "nix-command flakes",
                    "eval",
                    "--raw",
                    "/path/to/config#nixosConfigurations.hostname.config.system.build.toplevel.drvPath",
                ],
                check=True,
                stdout=PIPE,
                **DEFAULT_RUN_KWARGS,
            ),
            call(
                ["nix-copy-closure", "--to", "user@localhost", config_path],
                check=True,
                **DEFAULT_RUN_KWARGS,
            ),
            call(
                [
                    "ssh",
                    *nr.process.SSH_DEFAULT_OPTS,
                    "user@localhost",
                    "--",
                    "nix",
                    "--extra-experimental-features",
                    "'nix-command flakes'",
                    "build",
                    f"'{config_path}^*'",
                    "--print-out-paths",
                    "--no-link",
                ],
                check=True,
                stdout=PIPE,
                **DEFAULT_RUN_KWARGS,
            ),
            call(
                [
                    "nix-copy-closure",
                    "--from",
                    "user@localhost",
                    config_path,
                ],
                check=True,
                **DEFAULT_RUN_KWARGS,
            ),
            call(
                [
                    "nix-env",
                    "-p",
                    Path("/nix/var/nix/profiles/system"),
                    "--set",
                    config_path,
                ],
                check=True,
                **DEFAULT_RUN_KWARGS,
            ),
            call(
                [config_path / "bin/switch-to-configuration", "switch"],
                check=True,
                **DEFAULT_RUN_KWARGS,
            ),
        ]
    )


@patch(get_qualified_name(nr.process.subprocess.run), autospec=True)
def test_execute_switch_rollback(mock_run: Any, tmp_path: Path) -> None:
    nixpkgs_path = tmp_path / "nixpkgs"
    nixpkgs_path.touch()

    nr.execute(
        ["nixos-rebuild", "switch", "--rollback", "--install-bootloader", "--fast"]
    )

    assert mock_run.call_count >= 2
    # ignoring update_nixpkgs_rev calls
    mock_run.assert_has_calls(
        [
            call(
                [
                    "nix-env",
                    "--rollback",
                    "-p",
                    Path("/nix/var/nix/profiles/system"),
                ],
                check=True,
                **DEFAULT_RUN_KWARGS,
            ),
            call(
                [
                    Path("/nix/var/nix/profiles/system/bin/switch-to-configuration"),
                    "switch",
                ],
                check=True,
                **DEFAULT_RUN_KWARGS,
            ),
        ]
    )


@patch(get_qualified_name(nr.process.subprocess.run), autospec=True)
def test_execute_build(mock_run: Any, tmp_path: Path) -> None:
    config_path = tmp_path / "test"
    config_path.touch()
    mock_run.side_effect = [
        # nixos_build_flake
        CompletedProcess([], 0, str(config_path)),
    ]

    nr.execute(["nixos-rebuild", "build", "--no-flake", "--fast"])

    assert mock_run.call_count == 1
    mock_run.assert_has_calls(
        [
            call(
                [
                    "nix-build",
                    "<nixpkgs/nixos>",
                    "--attr",
                    "config.system.build.toplevel",
                ],
                check=True,
                stdout=PIPE,
                **DEFAULT_RUN_KWARGS,
            )
        ]
    )


@patch(get_qualified_name(nr.process.subprocess.run), autospec=True)
def test_execute_test_flake(mock_run: Any, tmp_path: Path) -> None:
    config_path = tmp_path / "test"
    config_path.touch()

    def run_side_effect(args: list[str], **kwargs: Any) -> CompletedProcess[str]:
        if args[0] == "nix":
            return CompletedProcess([], 0, str(config_path))
        else:
            return CompletedProcess([], 0)

    mock_run.side_effect = run_side_effect

    nr.execute(
        ["nixos-rebuild", "test", "--flake", "github:user/repo#hostname", "--fast"]
    )

    assert mock_run.call_count == 2
    mock_run.assert_has_calls(
        [
            call(
                [
                    "nix",
                    "--extra-experimental-features",
                    "nix-command flakes",
                    "build",
                    "--print-out-paths",
                    "github:user/repo#nixosConfigurations.hostname.config.system.build.toplevel",
                ],
                check=True,
                stdout=PIPE,
                **DEFAULT_RUN_KWARGS,
            ),
            call(
                [config_path / "bin/switch-to-configuration", "test"],
                check=True,
                **DEFAULT_RUN_KWARGS,
            ),
        ]
    )


@patch(get_qualified_name(nr.process.subprocess.run), autospec=True)
@patch(get_qualified_name(nr.nix.Path.exists, nr.nix), autospec=True, return_value=True)
@patch(get_qualified_name(nr.nix.Path.mkdir, nr.nix), autospec=True)
def test_execute_test_rollback(
    mock_path_mkdir: Any,
    mock_path_exists: Any,
    mock_run: Any,
) -> None:
    def run_side_effect(args: list[str], **kwargs: Any) -> CompletedProcess[str]:
        if args[0] == "nix-env":
            return CompletedProcess(
                [],
                0,
                stdout=textwrap.dedent("""\
                2082   2024-11-07 22:58:56
                2083   2024-11-07 22:59:41
                2084   2024-11-07 23:54:17   (current)
                """),
            )
        else:
            return CompletedProcess([], 0)

    mock_run.side_effect = run_side_effect

    nr.execute(
        ["nixos-rebuild", "test", "--rollback", "--profile-name", "foo", "--fast"]
    )

    assert mock_run.call_count == 2
    mock_run.assert_has_calls(
        [
            call(
                [
                    "nix-env",
                    "-p",
                    Path("/nix/var/nix/profiles/system-profiles/foo"),
                    "--list-generations",
                ],
                check=True,
                stdout=PIPE,
                **DEFAULT_RUN_KWARGS,
            ),
            call(
                [
                    Path(
                        "/nix/var/nix/profiles/system-profiles/foo-2083-link/bin/switch-to-configuration"
                    ),
                    "test",
                ],
                check=True,
                **DEFAULT_RUN_KWARGS,
            ),
        ]
    )
