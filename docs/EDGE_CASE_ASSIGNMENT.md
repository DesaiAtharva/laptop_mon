# Edge Case Assignment

> **Purpose:** Maps all 100 edge cases to the prompt that builds them and the test layer that proves them.
> Every edge case is swept again in T7. Platform-specific cases also require a manual test sheet.

| ID | Edge Case | Built In | Test Layer | Manual Sheet |
|---|---|---|---|---|
| E01 | No internet at startup | P5 | T4 | |
| E02 | Connection lost mid-upload | P2, P5 | T2 | |
| E03 | Batch committed but response lost | P2, P5 | T2 | |
| E04 | DNS failure or captive portal | P5 | T4 | |
| E05 | Proxy, VPN or firewall blocks API | P5 | T4 | |
| E06 | TLS certificate invalid or expired | P5, P10 | T4 | |
| E07 | Shutdown while online | P5 | T4 | |
| E08 | Hard power loss | P5 | T4 | |
| E09 | Agent killed during SQLite write | P5 | T4 | |
| E10 | Agent crashes repeatedly | P5 | T4 | |
| E11 | UI closed, agent continues | P5 | T4 | |
| E12 | Employee explicitly exits monitoring | P5 | T4 | |
| E13 | Uninstall with pending data | P5, P7 | T4 | |
| E14 | OS update or reboot | P7, P11 | T4 | |
| E15 | Agent update interrupted | P7 | T4 | |
| E16 | Agent and server version mismatch | P2, P7 | T2 | |
| E17 | Local disk full | P5 | T4 | |
| E18 | Local queue reaches quota | P5 | T4 | |
| E19 | SQLite corrupt | P5 | T4 | |
| E20 | Screenshot file without DB row | P5 | T4 | |
| E21 | DB row without screenshot file | P5 | T4 | |
| E22 | Encryption key unavailable | P5, P12 | T4 | |
| E23 | Device reimaged or profile deleted | P2, P5 | T2 | |
| E24 | Device stolen | P2 | T2 | |
| E25 | Device clock far off | P2, P4, P5 | T2 | |
| E26 | Clock changes while running | P4, P5 | T2 | |
| E27 | Timezone changes | P4, P5 | T2 | |
| E28 | DST 23 or 25 hour day | P4 | T1 | |
| E29 | Duplicate timestamps | P4 | T1 | |
| E30 | Events arrive out of order | P4 | T2 | |
| E31 | Duplicate event ID, same payload | P2 | T2 | |
| E32 | Duplicate event ID, different payload | P2 | T2 | |
| E33 | Unknown event type | P2 | T2 | |
| E34 | Oversized batch | P2, P5 | T2 | |
| E35 | Rate limit or overload | P2, P5 | T2 | |
| E36 | Partial batch acceptance | P2, P5 | T2 | |
| E37 | Policy changed while offline | P2, P5 | T4 | |
| E38 | Device revoked while offline | P2, P5 | T3 | |
| E39 | Enrollment token reused or expired | P2 | T5 | |
| E40 | Device credential leaked | P2 | T5 | |
| E41 | Employee moved to another team | P1, P8 | T3 | |
| E42 | Employee leaves company | P1, P9 | T3 | |
| E43 | Tenant suspended | P1, P9 | T3 | |
| E44 | Tenant deleted | P1, P9 | T2 | |
| E45 | Cross-tenant object ID guessed | P1 | T5 | |
| E46 | User in multiple tenants | P1, P8 | T3 | |
| E47 | Manager changes teams | P1, P8 | T3 | |
| E48 | Admin account compromised | P1, P10 | T5 | |
| E49 | Screenshot view URL leaked | P3 | T5 | |
| E50 | Malicious uploaded file | P3 | T5 | |
| E51 | Screenshot upload partially completes | P3 | T2 | |
| E52 | Upload succeeded, finalize failed | P3 | T2 | |
| E53 | Finalize succeeded, response lost | P3 | T2 | |
| E54 | Retention job fails | P3 | T2 | |
| E55 | Screenshot exclusion rule added | P3 | T2 | |
| E56 | OS permission denied or revoked | P5, P6, P11, P12 | T7 manual | docs/test-evidence/windows.md, macos.md, linux.md |
| E57 | Screen locked | P6 | T7 manual | docs/test-evidence/windows.md |
| E58 | Sleep, hibernate and wake | P4, P6 | T7 manual | docs/test-evidence/windows.md |
| E59 | Fast user switching | P5, P6, P11 | T7 manual | docs/test-evidence/windows.md, macos.md |
| E60 | Remote desktop or VDI | P6, P12 | T7 manual | docs/test-evidence/windows.md, linux.md |
| E61 | Multiple monitors and topology changes | P6, P11 | T7 manual | docs/test-evidence/windows.md, macos.md |
| E62 | Wayland and X11 capability mismatch | P12 | T7 manual | docs/test-evidence/linux.md |
| E63 | macOS permission reset | P11 | T7 manual | docs/test-evidence/macos.md |
| E64 | Windows secure desktop or UAC | P6 | T7 manual | docs/test-evidence/windows.md |
| E65 | Linux headless or unsupported desktop | P12 | T7 manual | docs/test-evidence/linux.md |
| E66 | App identifier unavailable | P4, P6 | T1 | |
| E67 | Window title has sensitive data | P5, P6 | T4 | |
| E68 | Screenshot has sensitive data | P5, P6 | T7 manual | docs/test-evidence/windows.md |
| E69 | App classification changes | P4, P8 | T3 | |
| E70 | Idle threshold changes | P4, P8 | T3 | |
| E71 | Session never receives end event | P4 | T1 | |
| E72 | Idle end without idle start | P4 | T1 | |
| E73 | Overlapping app intervals | P4 | T1 | |
| E74 | Late event changes daily totals | P4, P8 | T3 | |
| E75 | Worker retries same job | P4 | T4 | |
| E76 | Celery or Redis unavailable | P4 | T4 | |
| E77 | MySQL failover or deadlock | P4, P10 | T4 | |
| E78 | Database migration fails | P1, P10 | T4 | |
| E79 | Connection pool exhausted | P4 | T6 | |
| E80 | Stale or cross-tenant cache | P1, P10 | T5 | |
| E81 | Report query too large | P4 | T6 | |
| E82 | Export exceeds limits | P4 | T6 | |
| E83 | Invitation email delivery fails | P9 | T2 | |
| E84 | Payment webhook duplicated or out of order | P9 | T2 | |
| E85 | Subscription limit reached | P2, P9 | T2 | |
| E86 | Backup restore needed | P10 | T4 | |
| E87 | Region or provider outage | P10 | T4 | |
| E88 | Logs or crash dumps contain secrets | P5, P10 | T5 | |
| E89 | False positive or employee dispute | P8 | T3 | |
| E90 | Legal retention or deletion request | P3 | T2 | |
| E91 | Untrusted local administrator tampers | P7 | T5 | |
| E92 | Agent disabled by antivirus or EDR | P6, P7 | T7 manual | docs/test-evidence/windows.md |
| E93 | Monotonic clock reset after reboot | P5 | T4 | |
| E94 | Compression differs by OS | P5 | T6 | |
| E95 | Very large multi-monitor capture | P6 | T7 manual | docs/test-evidence/windows.md |
| E96 | Battery saver or CPU pressure | P5 | T6 | |
| E97 | Offline beyond retention or quota | P5 | T4 | |
| E98 | User changes OS account | P2, P5, P6 | T7 manual | docs/test-evidence/windows.md |
| E99 | Concurrent admin policy edits | P2, P8 | T3 | |
| E100 | Support staff accesses customer data | P1 | T5 | |
