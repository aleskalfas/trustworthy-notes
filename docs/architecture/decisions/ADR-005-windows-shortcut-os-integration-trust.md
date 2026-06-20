# ADR-005: Windows shortcut and OS-integration trust posture

- Status: Accepted
- Date: 2026-06-20

**In one minute:** first-run onboarding offers to create a "Send Feedback" desktop shortcut — the first time trustworthy-notes writes an OS-integration artifact onto the user's machine outside its own config and workspace. This extends ADR-001's distribution posture (an unsigned, self-upgrading exe trusting GitHub-over-TLS) to a new trust surface. We confine the Windows-specificity to a string handed to PowerShell — an OS program present on every Windows 10/11 — rather than bundling a COM library, so no new dependency enters the PyInstaller build. The shortcut is created only behind a one-tap onboarding confirm, never silently, and it targets the stable `tnotes.exe feedback` so it survives the upgrade rename.

## Context

`tnotes feedback` is the second-most-prominent thing a non-technical user does with the tool (after running the pipeline), but nothing surfaces it: there is no installer, no Start-menu entry, no account. To make feedback discoverable, first-run onboarding offers to drop a "Send Feedback" shortcut on the user's desktop.

This is a new kind of action for the tool. Until now, everything trustworthy-notes writes lands in its own config or workspace; a desktop `.lnk` is the first artifact it places into the user's OS shell — an **OS-integration artifact** outside its own footprint. That extends the trust posture ADR-001 already stated for distribution: an **unsigned**, self-replacing exe whose only trust root is GitHub plus TLS. Writing into the user's desktop is a smaller surface than self-rewriting over the network, but it is a surface, and creating it deserves the same deliberate posture rather than a silent side effect.

The forces in tension:

- **Discoverability of feedback for one non-technical user** versus adding any new machinery — a dependency, a silent OS write — to a tool whose whole shape is "one unsigned exe, no installer."
- **A shortcut is inherently a Windows-only artifact**, so some Windows-specificity is unavoidable; the question is where it lives and how tightly it is confined.
- **The shortcut must keep working across upgrades**, where ADR-001's swap renames the running exe (`tnotes.exe` → `.old` → new exe into the freed name). A shortcut that encodes the wrong target is orphaned by the very upgrade mechanism ADR-001 built.

## Decision

**A PowerShell shell-out, not a bundled COM library.** The shortcut is created by invoking `WScript.Shell.CreateShortcut` through `powershell -Command ...` as a subprocess — **not** by bundling a Windows COM Python library (`win32com` / `pywin32`). This keeps the Python side OS-neutral and adds **no new dependency to the PyInstaller bundle**, whose frozen-build correctness ADR-002 must otherwise keep intact. PowerShell ships on every Windows 10/11, so the dependency is the OS itself. Because a shortcut is inherently Windows-only, this confines the unavoidable Windows-specificity to a single string handed to an always-present OS program, **gated so it never runs off-Windows** — consistent with how `winlaunch.py` already gates its `GetConsoleProcessList` ctypes call behind a platform check.

**User-confirmed, never silent.** The shortcut is created only behind a **one-tap confirm during onboarding**. Nothing is written to the user's desktop without their agreement, matching the user-initiated principle ADR-001 applied to upgrades: the tool reports and offers, the human decides. A tool that silently plants OS artifacts is the behaviour we are deliberately not adopting.

**The target is the stable exe name plus subcommand, not a versioned path.** The shortcut points at `tnotes.exe feedback` — the stable executable name, not a versioned or absolute build path. This is what makes it survive ADR-001's upgrade swap: the upgrade renames the live exe out of the way and moves the new build into the **freed, stable name**, so a shortcut that targets that name keeps resolving across every upgrade. The failure mode this avoids is explicit: a shortcut encoding a versioned path that ADR-001's rename swap would orphan on the next upgrade.

## Consequences

- **The shortcut is a second launch entry point with its own trust posture.** Beyond the main pipeline launch, the user now has a desktop entry that maps directly to the `feedback` subcommand — and feedback carries a distinct trust posture from the pipeline (it can exfiltrate data, per ADR-003). The shortcut surfaces that path one tap from the desktop; it does not change what `feedback` does or the consent gate that stands in front of every upload.
- **A moved exe leaves a dangling shortcut.** If the user relocates `tnotes.exe`, the shortcut breaks. This is accepted: re-running onboarding (or re-creating the shortcut) is the recovery, and the alternative — chasing the exe's location — reintroduces exactly the brittle path-coupling the stable-name target avoids.
- **Shortcut creation is validated last, on real Windows.** macOS cannot validate `.lnk` creation at all — there is no shell to write to and no PowerShell semantics to exercise — so the code is authored with the Windows path gated and mocked, and the **first real validation is a Windows run of the frozen exe**. This mirrors `winlaunch.py`'s own honesty about its Windows-only console code and ADR-001's running-exe swap: a known validation gap carried deliberately, not an oversight.
- **Hand-writing the raw `.lnk` binary was considered and rejected.** Emitting the shortcut's binary format directly in pure Python would also add no dependency, but it reimplements an undocumented, fragile binary format that the OS already knows how to produce correctly. Delegating to `WScript.Shell` via PowerShell buys the same zero-dependency outcome while letting Windows own the format.
