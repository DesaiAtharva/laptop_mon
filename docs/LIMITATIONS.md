# LIMITATIONS.md

> **Purpose:** Documents known limitations, OS constraints, and deviations from the spec.
> Every entry must include: the limitation, the safe behavior implemented, and the test that proves the safe behavior.

| ID | Limitation | Safe Behavior | Test | Prompt |
|---|---|---|---|---|
| LIM-001 | SQLite WAL with `synchronous=NORMAL`: events since last checkpoint may be lost on hard power loss (E08) | Gap event written on next startup; loss window is bounded and documented (ADR-004) | `test_E08_hard_power_loss` | P5 |
| LIM-002 | Windows Secure Desktop and UAC prompts execute on isolated desktop session (E64) | Capture skipped safely; OpenInputDesktop detects desktop switch; never attempted or bypassed | `test_E64_windows_secure_desktop_or_uac` | P6 |
| LIM-003 | Lock screen contains sensitive credentials/notifications and is not captured by default (E57) | Screen capture skipped safely while workstation is locked; session.lock event logged | `test_E57_screen_locked_not_captured` | P6 |
| LIM-004 | Antivirus / EDR tools may flag unsigned monitoring software (E92) | Zero obfuscation or evasion techniques; binary signing and IT allowlisting documented | `test_E92_antivirus_allowlisting_documentation` | P6 |
| LIM-005 | Local administrator tampering with agent binaries, registry, or files (E91) | Agent self-verifies SHA-256 and signatures; rolls back or halts safely on corruption; backend marks missing telemetry as explicit unknown gaps | `test_E91_tampering_corrupted_binary_rollback_or_halt` | P7 |
