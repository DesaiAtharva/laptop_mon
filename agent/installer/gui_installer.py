"""Graphical Desktop Agent Setup & Enrollment Wizard.

Implements REQ-2-2, §2.1, §2.3:
- Displays transparent first-run notice and requires employee/student consent.
- Captures Employee/Student ID and Full Name to bind the laptop to the individual.
- Automatically enrolls the laptop with the organization's SaaS server.
- Registers Windows startup and launches the lightweight agent.
- Falls back to CLI interactive prompt if GUI display is unavailable.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Optional

# Ensure agent directory is importable
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent.installer.install import install


def run_cli_wizard(server_default: str, token_default: str) -> int:
    """Fallback interactive terminal wizard when GUI is not available."""
    print("=" * 60)
    print("  Laptop Productivity Monitoring — Onboarding Setup")
    print("=" * 60)
    print("Welcome! Please provide your details to enroll this laptop.")
    print("-" * 60)

    server = input(f"Server URL [{server_default}]: ").strip() or server_default
    token = input(f"Enrollment Token [{token_default}]: ").strip() or token_default
    if not token:
        print("Error: Enrollment token is required.")
        return 1

    emp_id = input("Employee or Student ID (e.g. STU-101 / EMP-042): ").strip()
    emp_name = input("Full Name: ").strip()

    print("\n--- Transparency & Permission Notice (REQ-2-2) ---")
    print("This laptop will monitor active application window titles and")
    print("capture periodic desktop screenshots during work hours.")
    print("No keystrokes, passwords, or personal messages are ever captured.")
    consent = input("\nDo you understand and grant monitoring permissions? (yes/no): ").strip().lower()
    if consent not in ("y", "yes"):
        print("Enrollment cancelled. Monitoring not started.")
        return 1

    print("\nInstalling and enrolling...")
    res = install(
        server=server,
        token=token,
        employee_id=emp_id,
        employee_name=emp_name,
        quiet=False,
    )
    if res.get("success"):
        print("\n[SUCCESS] Setup completed successfully! Monitoring is now active.")
        return 0
    else:
        print("\n[FAILED] Installation encountered an error.")
        return 1


def run_gui_wizard(server_default: str, token_default: str) -> int:
    """Render a clean, modern native Tkinter Setup Wizard."""
    try:
        import tkinter as tk
        from tkinter import messagebox, ttk
    except ImportError:
        return run_cli_wizard(server_default, token_default)

    root = tk.Tk()
    root.title("Laptop Productivity Monitoring — Setup Wizard")
    root.geometry("560x640")
    root.resizable(False, False)

    # Set modern dark styling colors
    bg_color = "#0f172a"
    card_bg = "#1e293b"
    accent_color = "#06b6d4"
    text_color = "#f8fafc"
    text_muted = "#94a3b8"
    entry_bg = "#090d16"
    border_color = "#334155"

    root.configure(bg=bg_color)

    style = ttk.Style()
    style.theme_use("clam")
    style.configure("TLabel", background=bg_color, foreground=text_color, font=("Segoe UI", 9))
    style.configure("Header.TLabel", font=("Segoe UI", 16, "bold"), foreground=accent_color, background=bg_color)
    style.configure("Sub.TLabel", font=("Segoe UI", 9), foreground=text_muted, background=bg_color)
    style.configure("Card.TFrame", background=card_bg)

    # Main Container
    container = tk.Frame(root, bg=bg_color, padx=25, pady=20)
    container.pack(fill="both", expand=True)

    # Header
    header_lbl = ttk.Label(container, text="Laptop Agent Enrollment", style="Header.TLabel")
    header_lbl.pack(anchor="w")

    sub_lbl = ttk.Label(
        container,
        text="Bind this managed laptop to your organization with your Employee/Student ID.",
        style="Sub.TLabel",
    )
    sub_lbl.pack(anchor="w", pady=(3, 15))

    # Form Frame
    form_frame = tk.Frame(container, bg=card_bg, padx=18, pady=16, highlightthickness=1, highlightbackground=border_color)
    form_frame.pack(fill="x", pady=5)

    def make_field(parent: tk.Widget, label_text: str, default_val: str = "", show: Optional[str] = None) -> tk.Entry:
        lbl = tk.Label(parent, text=label_text, bg=card_bg, fg=text_color, font=("Segoe UI", 9, "bold"))
        lbl.pack(anchor="w", pady=(6, 2))
        entry = tk.Entry(
            parent,
            bg=entry_bg,
            fg=text_color,
            insertbackground=text_color,
            font=("Segoe UI", 10),
            relief="flat",
            highlightthickness=1,
            highlightbackground=border_color,
            highlightcolor=accent_color,
        )
        if show:
            entry.configure(show=show)
        if default_val:
            entry.insert(0, default_val)
        entry.pack(fill="x", ipady=5, pady=(0, 4))
        return entry

    ent_server = make_field(form_frame, "Cloud Server URL:", server_default)
    ent_token = make_field(form_frame, "Organization Enrollment Token:", token_default)
    ent_emp_id = make_field(form_frame, "Employee or Student ID (e.g. STU-101 / EMP-042):", "")
    ent_emp_name = make_field(form_frame, "Employee or Student Full Name:", "")

    # Transparency Notice Box (REQ-2-2)
    notice_frame = tk.Frame(
        container,
        bg="#132338",
        padx=14,
        pady=10,
        highlightthickness=1,
        highlightbackground="rgba(6, 182, 212, 0.4)",
    )
    notice_frame.pack(fill="x", pady=(14, 10))

    notice_title = tk.Label(
        notice_frame,
        text="ℹ️ Transparent Monitoring & Privacy Consent (REQ-2-2)",
        bg="#132338",
        fg=accent_color,
        font=("Segoe UI", 9, "bold"),
    )
    notice_title.pack(anchor="w")

    notice_body = (
        "• This laptop will monitor active application window titles and desktop focus.\n"
        "• Periodic desktop screenshot captures are stored securely for productivity verification.\n"
        "• NO keystrokes, passwords, or personal chat scraping are ever performed.\n"
        "• You can review all logged data at any time in the Employee Self-View portal."
    )
    notice_txt = tk.Label(
        notice_frame,
        text=notice_body,
        bg="#132338",
        fg=text_muted,
        font=("Segoe UI", 8),
        justify="left",
    )
    notice_txt.pack(anchor="w", pady=(4, 6))

    consent_var = tk.BooleanVar(value=True)
    chk_consent = tk.Checkbutton(
        notice_frame,
        text="I acknowledge and grant permission for productivity monitoring on this laptop.",
        variable=consent_var,
        bg="#132338",
        fg=text_color,
        selectcolor=bg_color,
        activebackground="#132338",
        activeforeground=text_color,
        font=("Segoe UI", 8, "bold"),
    )
    chk_consent.pack(anchor="w")

    # Status Message
    lbl_status = tk.Label(container, text="", bg=bg_color, fg=accent_color, font=("Segoe UI", 9))
    lbl_status.pack(pady=4)

    exit_code = [0]

    def on_submit() -> None:
        server = ent_server.get().strip()
        token = ent_token.get().strip()
        emp_id = ent_emp_id.get().strip()
        emp_name = ent_emp_name.get().strip()

        if not server:
            messagebox.showerror("Validation Error", "Please provide the Server URL.")
            return
        if not token:
            messagebox.showerror("Validation Error", "Please provide the Enrollment Token.")
            return
        if not emp_id:
            messagebox.showwarning("Notice", "Please enter your Employee or Student ID so your device is recognized.")
            return
        if not emp_name:
            messagebox.showwarning("Notice", "Please enter your Full Name.")
            return
        if not consent_var.get():
            messagebox.showerror("Permission Required", "You must acknowledge and consent to monitoring before installation.")
            return

        lbl_status.config(text="Connecting to server and enrolling laptop...")
        root.update()

        try:
            res = install(
                server=server,
                token=token,
                employee_id=emp_id,
                employee_name=emp_name,
                quiet=True,
            )
            if res.get("success"):
                messagebox.showinfo(
                    "Setup Complete",
                    f"Laptop successfully enrolled!\n\n"
                    f"Employee ID: {emp_id}\n"
                    f"Name: {emp_name}\n"
                    f"Organization Server: {server}\n\n"
                    f"Productivity monitoring is now active in the background.",
                )
                exit_code[0] = 0
                root.destroy()
            else:
                messagebox.showerror("Installation Error", "Installation could not complete. Check server connection.")
                lbl_status.config(text="Installation failed.")
        except Exception as err:
            messagebox.showerror("Error", f"Failed: {err}")
            lbl_status.config(text=f"Error: {err}")

    # Install Button
    btn_install = tk.Button(
        container,
        text="Grant Permissions & Complete Setup",
        bg=accent_color,
        fg="#0a0e17",
        font=("Segoe UI", 11, "bold"),
        relief="flat",
        cursor="pointer",
        activebackground="#0891b2",
        activeforeground="#ffffff",
        command=on_submit,
        pady=8,
    )
    btn_install.pack(fill="x", pady=(8, 0))

    root.mainloop()
    return exit_code[0]


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Laptop Productivity Monitoring GUI Setup Wizard")
    parser.add_argument("--server", default="https://monitor.saptasuryasolar.com", help="Backend server URL")
    parser.add_argument("--token", default="", help="Single-use enrollment token")
    parser.add_argument("--cli", action="store_true", help="Force interactive CLI mode")
    args = parser.parse_args(argv)

    if args.cli or not os.environ.get("DISPLAY") and sys.platform != "win32":
        return run_cli_wizard(args.server, args.token)
    return run_gui_wizard(args.server, args.token)


if __name__ == "__main__":
    sys.exit(main())
