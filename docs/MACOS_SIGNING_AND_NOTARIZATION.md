# macOS Code Signing, Hardened Runtime, and Notarization Guide

## 1. Overview
As mandated by **SPEC §15.1** and Apple macOS Gatekeeper requirements (macOS 10.15 Catalina and newer), all native macOS applications distributed outside the Mac App Store must be:
1. Signed with an Apple **Developer ID Application** certificate.
2. Compiled with the **Hardened Runtime** enabled (`--options runtime`).
3. Accompanied by hardened security entitlements.
4. Notarized by Apple's automated Notary Service via `xcrun notarytool`.
5. Stapled with the cryptographic notarization ticket via `xcrun stapler`.

---

## 2. Certificate Requirements

Two Apple certificates are required:
- **Developer ID Application:** Signs the inner binary and `.app` bundle (`codesign`).
- **Developer ID Installer:** Signs the `.pkg` distribution installer (`productbuild` / `pkgbuild`).

---

## 3. Entitlements (`entitlements.plist`)

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <!-- Allows Python runtime JIT compilation under hardened runtime -->
    <key>com.apple.security.cs.allow-jit</key>
    <true/>
    <key>com.apple.security.cs.allow-unsigned-executable-memory</key>
    <false/>
    <key>com.apple.security.cs.disable-library-validation</key>
    <false/>
    <!-- Permits sending AppleEvents to frontmost applications to resolve foreground window -->
    <key>com.apple.security.automation.apple-events</key>
    <true/>
</dict>
</plist>
```

---

## 4. Signing Procedure

```bash
# 1. Sign all embedded frameworks and dylibs
find LaptopMon.app/Contents/Frameworks -type f -name "*.dylib" -exec \
    codesign --force --options runtime --timestamp --sign "Developer ID Application: Your Org (TEAMID)" {} \;

# 2. Sign main app bundle
codesign --force --options runtime --timestamp \
    --entitlements agent/packaging/entitlements.plist \
    --sign "Developer ID Application: Your Org (TEAMID)" \
    LaptopMon.app

# 3. Verify signing
codesign --verify --deep --strict --verbose=2 LaptopMon.app
spctl --assess --type execute --verbose LaptopMon.app
```

---

## 5. Notarization & Stapling Workflow

Store Apple ID credentials in the macOS Keychain:
```bash
xcrun notarytool store-credentials "AC_PASSWORD" \
    --apple-id "builder@yourorg.com" \
    --team-id "TEAMID" \
    --password "app-specific-password"
```

Submit for notarization:
```bash
xcrun notarytool submit LaptopMon-1.0.0.pkg \
    --keychain-profile "AC_PASSWORD" \
    --wait
```

Staple the ticket to the installer:
```bash
xcrun stapler staple LaptopMon-1.0.0.pkg
spctl --assess --type install --verbose LaptopMon-1.0.0.pkg
```
