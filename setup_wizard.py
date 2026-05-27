#!/usr/bin/env python3
"""
OCI-OcC-Fix interactive setup wizard.
Guides users through configuration.ini and OCI SDK config file setup.
"""

import argparse
import configparser
import json
import os
import re
import sys
import textwrap
from pathlib import Path
from typing import Dict, Optional, Tuple

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, simpledialog
except Exception:  # pragma: no cover - optional GUI support
    tk = None

CONFIG_FILE = "configuration.ini"
OCI_CONFIG_FILE = "config"


def _wrap(text: str) -> str:
    return textwrap.fill(text, width=90)


def _print_header(title: str) -> None:
    print("\n" + "=" * 90)
    print(title)
    print("=" * 90)


def _prompt(prompt: str) -> str:
    return input(prompt).strip()


def _confirm(prompt: str, default: bool = False) -> bool:
    default_hint = "Y/n" if default else "y/N"
    while True:
        value = _prompt(f"{prompt} ({default_hint}): ").lower()
        if not value:
            return default
        if value in {"y", "yes"}:
            return True
        if value in {"n", "no"}:
            return False
        print("Please enter y or n.")


def _validate_json_array(value: str) -> Tuple[bool, str]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return False, "Enter a valid JSON array (e.g. [\"AD-1\",\"AD-2\"])."
    if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
        return False, "Availability domains must be a JSON array of strings."
    return True, ""


def _to_json_array(value: str) -> Tuple[bool, str]:
    if value.strip().startswith("["):
        ok, message = _validate_json_array(value)
        if not ok:
            return False, message
        return True, json.dumps(json.loads(value), separators=(",", ":"))
    parts = [part.strip() for part in value.split(",") if part.strip()]
    if not parts:
        return False, "Enter at least one availability domain."
    return True, json.dumps(parts, separators=(",", ":"))


def _read_config_values(path: Path) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(interpolation=None)
    if path.exists():
        parser.read(path)
    return parser


def _normalize_default(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    value = value.strip()
    return value if value else None


def _update_ini_lines(
    lines: list,
    section: str,
    updates: Dict[str, str],
    default_separator: str = " = ",
) -> list:
    section_header = re.compile(r"^\s*\[" + re.escape(section) + r"\]\s*$")
    any_header = re.compile(r"^\s*\[[^\]]+\]\s*$")
    section_start = None
    for idx, line in enumerate(lines):
        if section_header.match(line):
            section_start = idx
            break

    if section_start is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append(f"[{section}]")
        section_start = len(lines) - 1

    section_end = len(lines)
    for idx in range(section_start + 1, len(lines)):
        if any_header.match(lines[idx]):
            section_end = idx
            break

    remaining = dict(updates)
    for idx in range(section_start + 1, section_end):
        line = lines[idx]
        if line.lstrip().startswith(("#", ";")):
            continue
        for key in list(remaining.keys()):
            pattern = re.compile(rf"^(\s*{re.escape(key)}\s*=\s*)(.*)$")
            match = pattern.match(line)
            if match:
                lines[idx] = f"{match.group(1)}{remaining.pop(key)}"
                break

    insert_at = section_end
    for key, value in remaining.items():
        lines.insert(insert_at, f"{key}{default_separator}{value}")
        insert_at += 1

    return lines


def _write_updates(path: Path, updates: Dict[str, Dict[str, str]], default_separator: str) -> None:
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    for section, values in updates.items():
        lines = _update_ini_lines(lines, section, values, default_separator=default_separator)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class SetupWizard:
    def __init__(self, config_path: Path, oci_config_path: Path, use_gui: bool) -> None:
        self.config_path = config_path
        self.oci_config_path = oci_config_path
        self.config_parser = _read_config_values(config_path)
        self.oci_parser = _read_config_values(oci_config_path)
        self.gui_root = None
        self.use_gui = use_gui
        self._init_gui()

    def _init_gui(self) -> None:
        if not self.use_gui or tk is None:
            return
        try:
            self.gui_root = tk.Tk()
            self.gui_root.withdraw()
        except Exception:
            self.gui_root = None
            self.use_gui = False
            print("GUI not available. Falling back to CLI mode.")

    def _show_info(self, title: str, message: str) -> None:
        if self.use_gui and self.gui_root:
            messagebox.showinfo(title, message, parent=self.gui_root)
            return
        _print_header(title)
        print(_wrap(message))

    def _ask_yes_no(self, prompt: str, default: bool = False) -> bool:
        if self.use_gui and self.gui_root:
            return messagebox.askyesno("Confirm", prompt, parent=self.gui_root)
        return _confirm(prompt, default=default)

    def _ask_text(
        self,
        label: str,
        default: Optional[str],
        required: bool,
        validator=None,
    ) -> str:
        while True:
            if self.use_gui and self.gui_root:
                value = simpledialog.askstring(
                    "Input Required" if required else "Input",
                    f"{label}\n\nDefault: {default or ''}",
                    initialvalue=default or "",
                    parent=self.gui_root,
                )
                if value is None:
                    self._abort("Wizard cancelled by user.")
                value = value.strip()
            else:
                prompt = f"{label}"
                if default:
                    prompt += f" [{default}]"
                prompt += ": "
                value = _prompt(prompt)
                if not value and default is not None:
                    value = default

            if not value and required:
                self._show_info("Input Needed", "This value is required.")
                continue

            if validator:
                ok, message = validator(value)
                if not ok:
                    self._show_info("Invalid Input", message)
                    continue
            return value

    def _ask_file(self, label: str, default: Optional[str]) -> str:
        if self.use_gui and self.gui_root:
            path = filedialog.askopenfilename(title=label, parent=self.gui_root)
            if not path:
                if default:
                    return default
                self._abort("A file path is required.")
            return path
        return self._ask_text(label, default=default, required=not bool(default))

    def _abort(self, message: str) -> None:
        if self.use_gui and self.gui_root:
            messagebox.showerror("Setup Cancelled", message, parent=self.gui_root)
        else:
            print(message)
        raise SystemExit(1)

    def run(self) -> None:
        self._show_info(
            "OCI-OcC-Fix Setup Wizard",
            "This wizard will guide you step-by-step and update configuration.ini "
            "and the OCI SDK config file (config).",
        )

        self._step_oci_api_config()
        self._step_oci_config()
        self._step_instance_config()
        self._step_telegram_config()
        self._step_machine_config()
        self._step_logging_config()
        self._confirm_and_write()

        self._show_info(
            "Setup Complete",
            "Your configuration has been updated. You can now run: python3 bot.py",
        )

    def _step_oci_api_config(self) -> None:
        self._show_info(
            "Step 1: OCI API Key (config)",
            "In the OCI Console, go to Identity > Users > Your User. Create or "
            "use an existing API key, and download the private key file. You will "
            "need the User OCID, Tenancy OCID, API key fingerprint, region, and "
            "the private key file path.",
        )

        defaults = self.oci_parser["DEFAULT"] if self.oci_parser.has_section("DEFAULT") else {}
        user = self._ask_text(
            "User OCID",
            _normalize_default(defaults.get("user")),
            required=True,
        )
        fingerprint = self._ask_text(
            "API key fingerprint",
            _normalize_default(defaults.get("fingerprint")),
            required=True,
        )
        tenancy = self._ask_text(
            "Tenancy OCID",
            _normalize_default(defaults.get("tenancy")),
            required=True,
        )
        region = self._ask_text(
            "Region identifier (example: us-ashburn-1)",
            _normalize_default(defaults.get("region")),
            required=True,
        )
        key_file = self._ask_file(
            "Private key file path (PEM)",
            _normalize_default(defaults.get("key_file")),
        )
        key_file = str(Path(key_file).expanduser())

        self.oci_updates = {
            "DEFAULT": {
                "user": user,
                "fingerprint": fingerprint,
                "tenancy": tenancy,
                "region": region,
                "key_file": key_file,
            }
        }

    def _step_oci_config(self) -> None:
        self._show_info(
            "Step 2: OCI Instance Request Details (configuration.ini)",
            "Create an instance in the OCI Console. When you see the Out of Capacity "
            "error, open browser developer tools > Network, find the /instances "
            "request, and copy it as cURL. The values below can be found in that "
            "request body.",
        )

        defaults = self.config_parser["OCI"] if self.config_parser.has_section("OCI") else {}

        use_boot = self._ask_yes_no("Do you want to use an existing boot volume?")
        if use_boot:
            boot_volume_id = self._ask_text(
                "Boot volume OCID (boot_volume_id)",
                _normalize_default(defaults.get("boot_volume_id")),
                required=True,
            )
            image_id = "xxxx"
        else:
            image_id = self._ask_text(
                "Image OCID (image_id)",
                _normalize_default(defaults.get("image_id")),
                required=True,
            )
            boot_volume_id = "xxxx"

        availability_domains_raw = self._ask_text(
            "Availability Domains (comma-separated or JSON array)",
            _normalize_default(defaults.get("availability_domains")),
            required=True,
            validator=self._validate_availability_domains,
        )
        ok, availability_domains = _to_json_array(availability_domains_raw)
        if not ok:
            self._abort(availability_domains)

        compartment_id = self._ask_text(
            "Compartment OCID (compartment_id)",
            _normalize_default(defaults.get("compartment_id")),
            required=True,
        )
        subnet_id = self._ask_text(
            "Subnet OCID (subnet_id)",
            _normalize_default(defaults.get("subnet_id")),
            required=True,
        )

        self.oci_config_updates = {
            "OCI": {
                "image_id": image_id,
                "availability_domains": availability_domains,
                "compartment_id": compartment_id,
                "subnet_id": subnet_id,
                "boot_volume_id": boot_volume_id,
            }
        }

    def _step_instance_config(self) -> None:
        self._show_info(
            "Step 3: Instance Settings",
            "Set the instance name and SSH key. The SSH key must be the public key "
            "you want on the instance (often in ~/.ssh/id_rsa.pub).",
        )

        defaults = self.config_parser["Instance"] if self.config_parser.has_section("Instance") else {}

        display_name = self._ask_text(
            "Instance display name (display_name)",
            _normalize_default(defaults.get("display_name")),
            required=True,
        )
        ssh_keys = self._ask_text(
            "Public SSH key (ssh_keys)",
            _normalize_default(defaults.get("ssh_keys")),
            required=True,
        )
        boot_volume_size = self._ask_text(
            "Boot volume size in GB (47-200, use 0 for default)",
            _normalize_default(defaults.get("boot_volume_size")) or "0",
            required=True,
            validator=self._validate_int,
        )

        self.instance_updates = {
            "Instance": {
                "display_name": display_name,
                "ssh_keys": ssh_keys,
                "boot_volume_size": boot_volume_size,
            }
        }

    def _step_telegram_config(self) -> None:
        self._show_info(
            "Step 4: Telegram Notifications (Optional)",
            "If you want Telegram updates: message @BotFather, run /newbot, then "
            "copy the token. For your user ID, message @Rose-Bot and send /id.",
        )

        defaults = self.config_parser["Telegram"] if self.config_parser.has_section("Telegram") else {}

        enable = self._ask_yes_no("Enable Telegram notifications?")
        if not enable:
            bot_token = "xxxx"
            uid = "xxxx"
        else:
            bot_token = self._ask_text(
                "Telegram bot token (bot_token)",
                _normalize_default(defaults.get("bot_token")),
                required=True,
            )
            uid = self._ask_text(
                "Telegram user ID (uid)",
                _normalize_default(defaults.get("uid")),
                required=True,
            )

        self.telegram_updates = {
            "Telegram": {
                "bot_token": bot_token,
                "uid": uid,
            }
        }

    def _step_machine_config(self) -> None:
        self._show_info(
            "Step 5: Machine Configuration",
            "Choose the machine type (ARM or AMD) and match the shape, OCPUs, and "
            "memory with what you selected in the OCI Create Instance page.",
        )

        defaults = self.config_parser["Machine"] if self.config_parser.has_section("Machine") else {}

        machine_type = self._ask_text(
            "Machine type (ARM or AMD)",
            _normalize_default(defaults.get("type")),
            required=True,
            validator=self._validate_machine_type,
        ).upper()
        shape = self._ask_text(
            "Compute shape (shape)",
            _normalize_default(defaults.get("shape")),
            required=True,
        )
        ocpus = self._ask_text(
            "OCPUs (ocpus)",
            _normalize_default(defaults.get("ocpus")),
            required=True,
            validator=self._validate_int,
        )
        memory = self._ask_text(
            "Memory in GB (memory)",
            _normalize_default(defaults.get("memory")),
            required=True,
            validator=self._validate_int,
        )

        self.machine_updates = {
            "Machine": {
                "type": machine_type,
                "shape": shape,
                "ocpus": ocpus,
                "memory": memory,
            }
        }

    def _step_logging_config(self) -> None:
        self._show_info(
            "Step 6: Logging Level",
            "INFO is recommended. Use DEBUG if you need more detailed logs.",
        )
        defaults = self.config_parser["Logging"] if self.config_parser.has_section("Logging") else {}
        log_level = self._ask_text(
            "Log level (DEBUG/INFO/WARNING/ERROR)",
            _normalize_default(defaults.get("log_level")) or "INFO",
            required=True,
            validator=self._validate_log_level,
        ).upper()

        self.logging_updates = {"Logging": {"log_level": log_level}}

    @staticmethod
    def _validate_int(value: str) -> Tuple[bool, str]:
        if not value:
            return False, "Enter a number."
        if not value.isdigit():
            return False, "Enter a valid integer."
        return True, ""

    @staticmethod
    def _validate_machine_type(value: str) -> Tuple[bool, str]:
        if value.upper() not in {"ARM", "AMD"}:
            return False, "Enter ARM or AMD."
        return True, ""

    @staticmethod
    def _validate_availability_domains(value: str) -> Tuple[bool, str]:
        ok, message = _to_json_array(value)
        return ok, message if not ok else ""

    @staticmethod
    def _validate_log_level(value: str) -> Tuple[bool, str]:
        if value.upper() not in {"DEBUG", "INFO", "WARNING", "ERROR"}:
            return False, "Use DEBUG, INFO, WARNING, or ERROR."
        return True, ""

    def _confirm_and_write(self) -> None:
        self._show_info(
            "Ready to Save",
            "The wizard will now write updates to configuration.ini and config. "
            "A backup (.bak) will be created for each file.",
        )
        if not self._ask_yes_no("Write configuration files now?"):
            self._abort("No changes were written.")

        for path in [self.config_path, self.oci_config_path]:
            if path.exists():
                backup = path.with_suffix(path.suffix + ".bak")
                backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")

        config_updates = {}
        config_updates.update(self.oci_config_updates)
        config_updates.update(self.instance_updates)
        config_updates.update(self.telegram_updates)
        config_updates.update(self.machine_updates)
        config_updates.update(self.logging_updates)

        _write_updates(self.config_path, config_updates, default_separator=" = ")
        _write_updates(self.oci_config_path, self.oci_updates, default_separator="=")


def main() -> None:
    parser = argparse.ArgumentParser(description="OCI-OcC-Fix setup wizard")
    parser.add_argument(
        "--config",
        default=CONFIG_FILE,
        help="Path to configuration.ini",
    )
    parser.add_argument(
        "--oci-config",
        default=OCI_CONFIG_FILE,
        help="Path to OCI SDK config file (default: ./config)",
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="Use simple graphical dialogs (requires tkinter).",
    )
    args = parser.parse_args()

    config_path = Path(args.config).expanduser().resolve()
    oci_config_path = Path(args.oci_config).expanduser().resolve()

    wizard = SetupWizard(config_path, oci_config_path, use_gui=args.gui)
    wizard.run()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nSetup cancelled.")
        sys.exit(1)
