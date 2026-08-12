# OSS survey dossier

Five parallel surveys, every candidate adversarially verified against the real
repository (GitHub API, clones, and on-machine probes) rather than search snippets.
Produced by a 34-agent swarm on 2026-08-12. Verdicts: ADOPT / TRIAL / REJECT.


## Lens: leap-native-oss

The ecosystem has a sharp fault line: almost everything with stars and history targets Gemini v5 (`libLeapC.5`) on Windows/Linux and is effectively dead for this machine, while the only two repos that explicitly target Hyperion v6 on macOS — `studiome/LeapSwift` (Swift, 2026-08-03) and `studiome/leapgo` (Go, 2026-07-30) — were written in the last three weeks by one author and have zero stars. Both READMEs claim a Leap Motion Controller 2 is required, but I read their device-enumeration code (`LeapController.swift`, `leapc/shim.c`) and confirmed neither filters on device type or PID: both call `LeapGetDeviceList` then `LeapOpenDevice(refs[0])` unconditionally, so the LMC2 line is stale README boilerplate inherited from Ultraleap's pre-6.2 marketing, not a code constraint — they should work with the verified LP20006680004. Ultraleap's own first-party stack is uniformly abandoned for this use case: `leapc-python-bindings` last pushed 2024-06-24 and is Gemini-only, `TouchFree` was archived 2023-04-21 with all 11 forks dead by 2023 (no cross-platform fork exists), and `LeapCxx` is a LeapSDK-4.x compatibility shim. The already-verified `DDlabAU/LeapMotion-Python-Hyperion` remains the only proven Python path and the only repo in the entire survey with confirmed working status on this exact hardware. Above the capture layer there is essentially nothing reusable — no maintained macOS gesture-recognition or action-injection library exists for Leap; the gesture-control topic is saturated with MediaPipe/PyAutoGUI webcam toys, and the one Leap-native end-to-end mouse app (`henry-richard7/leapmotion-app`) ships a `win_amd64`-only wheel. The realistic architecture is therefore: proven Python capture (DDlabAU) or new-but-clean typed capture (LeapSwift/leapgo), with gesture recognition and CGEventPost injection written in-house.

| Candidate | Layer | Verdict | Last activity |
|---|---|---|---|
| [studiome/LeapSwift](https://github.com/studiome/LeapSwift) | capture | **ADOPT** | 2026-08-03 (pushed_at); created 2026-07-26, 27 commits |
| [studiome/leapgo](https://github.com/studiome/leapgo) | capture | **ADOPT** | 2026-07-30 (pushed_at); MIT |
| [DDlabAU/LeapMotion-Python-Hyperion](https://github.com/DDlabAU/LeapMotion-Python-Hyperion) | capture | **ADOPT** | 2025-10-22 ('finished guide'); README states last tested 09/10-2025 on Windows and macOS |
| [ultraleap/leapc-python-bindings](https://github.com/ultraleap/leapc-python-bindings) | capture | **TRIAL** | 2024-06-24 (pushed_at); last actual code commit 2023-11-17. Repo metadata updated 2026-07-10 but no code movement in 2 years |
| [ultraleap/TouchFree](https://github.com/ultraleap/TouchFree) | end-to-end | **REJECT** | ARCHIVED 2023-04-21 (read-only). Sibling ultraleap/TouchFree-Current archived 2023-05-23 |
| [ultraleap/UltraleapTrackingWebSocket](https://github.com/ultraleap/UltraleapTrackingWebSocket) | transport | **—** | 2025-02-19 (pushed_at); repo metadata touched 2026-07-23; 17 stars, 6 forks, 4 open issues |
| [leapmotion/leapjs](https://github.com/leapmotion/leapjs) | transport | **—** | v1.0.0 maintenance release (dependency refresh for deprecated/archived packages and security advisories; explicitly no new features or fixes); exact date not established |
| [5of12/cacophony](https://github.com/5of12/cacophony) | gesture-recognition | **—** | 2026-01-20 (pushed_at); 5 stars, MIT. Playground last pushed 2025-04-22 |
| [henry-richard7/leapmotion-app](https://github.com/henry-richard7/leapmotion-app) | end-to-end | **—** | 2026-03-10 (pushed_at); created 2026-03-09 — a one-day project, 7 commits |
| [coleman-sagil/IntuiMotion](https://github.com/coleman-sagil/IntuiMotion) | end-to-end | **—** | ~2026-08-02 (pushed_at); in-repo notes reference 2026-07-27 boundary calibration and 2026-08-01 camera integration; 28 commits, 1 star |
| [bee-pollen/Leap-Motion-for-Mac](https://github.com/bee-pollen/Leap-Motion-for-Mac) | capture | **—** | 2026-01-24 (updated); 8 commits, 1 star, C |
| [plule/leaprs (+ urholaukkarinen/leap-sys)](https://github.com/plule/leaprs) | capture | **—** | leaprs 2025-03-03 (pushed_at), 16 stars, Apache-2.0/MIT dual; leap-sys 2022-07-13, 7 stars, MIT — effectively dead |
| [Komposten/LeapJna](https://github.com/Komposten/LeapJna) | capture | **—** | 2026-01-26 (repo updated); latest release 1.2.0 tracking SDK 5.6.1.0; 8 stars, MIT |
| [leapmotion/LeapCxx](https://github.com/leapmotion/LeapCxx) | capture | **—** | unknown — 155 commits on master, no dated commit recoverable; not archived but no evidence of modern activity |
| [ozankaraali/Handroller](https://github.com/ozankaraali/Handroller) | action-injection | **—** | 27 commits on main; exact date not established; 2 stars, MIT |

### studiome/LeapSwift — ADOPT

```
Not stale 2014-era content — repo is 17 days old and I proved it works on the target hardware in this session.

REPO FACTS (gh api repos/studiome/LeapSwift, clone at /private/tmp/claude-501/-Users-joerup-era-era-memory-evals/1f99f28d-32a3-423c-93b9-1778e24655e6/scratchpad/LeapSwift):
- created 2026-07-26T12:32:20Z, pushed_at 2026-08-03T02:23:56Z, head commit 961bcce dated 2026-08-03 ("Fix roll/pitch/yaw doc links"). 27 commits, all by one author, Kazuhiro Miyahara.
- 5 real releases: tags 0.1.0/0.1.1/0.1.2/0.1.3 (2026-07-27) and 0.1.4 (published 2026-08-03T02:02:56Z). MIT, not archived, not a fork.
- 0 stars, 0 forks, 0 watchers, 0 issues (open OR closed — `gh api issues?state=all` returned empty), 0 PRs. Author has 1 follower, 26 repos. Zero external adoption; the empty issue tracker is absence of users, not evidence of health. No .github/ directory at all — no CI.
- Same author also owns `leapgo` (Go, pushed 2026-07-30), so this is an active current interest, not a drive-by.

BUILT AND RAN ON THIS MACHINE (arm64, macOS 26.5.2, Swift 6.3.3, target arm64-apple-macosx26.0):
- `swift build` → "Build complete! (19.81s)", zero errors, WITHOUT Xcode installed (this box has only /Library/Developer/CommandLineTools; xcodebuild is unavailable). README's "Xcode 16.0 or later to build" is unnecessary for the SPM path.
- Consumer binary links `@rpath/libLeapC.6.dylib` (otool -L), `lipo -archs` → arm64. Correct SONAME .6 for Hyperion, resolved via the runpath into /Applications/Ultraleap Hand Tracking.app/Contents/LeapSDK/lib. That dylib is `Mach-O 64-bit arm64` (not universal), consistent with the framework being arm64-native here.

LIVE DEVICE TEST — the decisive result (probe at /private/tmp/claude-501/-Users-joerup-era-era-memory-evals/1f99f28d-32a3-423c-93b9-1778e24655e6/scratchpad/LiveProbe):
- 600 tracking frames in 5.40 s = 111.1 fps, first frame 0.04 s after connect. That is an exact match for the ground-truth ~111 fps measured through the Python bindings, from the ORI
```

**Corrections:** Four corrections, one of them significant:

1. SIGNIFICANT — the README is WRONG about hardware, in a way that would have caused a false reject. It states "A Leap Motion Controller 2, the device Hyperion supports" and "Ultraleap also states that Hyperion needs a Leap Motion Controller 2 and does not support the original Leap Motion Controller, for which Gemini v5 remains the current software." That is stale relative to Hyperion 6.2, which re-added v1 support. I ran LeapSwift against the original 2013 LMC and got serial LP20006680004 at 111.1 fps. There is no device gating in the code — `grep -rEn "LMC|DevicePID|deviceType|device_type|PID_"` over LeapSwift/ returns zero hits; openFirstDevice() just takes refs[0] from LeapGetDeviceList. The LMC2 requirement is prose, not a constraint. Do not let this README paragraph disqualify the candidate.

2. The surveyor's "README states Intel and Apple Silicon builds are both provided" is a misattribution. That sentence in the README is describing Ultraleap Hyperion's own installer, not LeapSwift builds. LeapSwift ships no binaries at all — it is source-only and builds for whatever arch you compile on. The conclusion (arm64 works) is right; the cited reason is wrong.

3. Mock scenario names are slightly off. Actual cases are `.noHands`, `.idleRightHand`, `.bothHandsIdle`, `.openClose`, `.pinch`, `.wave` — the surveyor wrote "idle" and "bothHands". Count of 6 is correct.

4. "requires Xcode 16+" is over-strict for the SPM path — it built cleanly here with Command Line Tools only and no Xcode. Xcode IS required to run the test suite (swift-testing module) and to build the .xcodeproj/DocC, so the requirement is real for those, not for consuming the library.

Also worth flagging for the orchestrator, not a correction: "claimed layer: capture" is accurate and limiting. This is purely a LeapC binding — it gives you frames, hands, fingers, palm position/orientation, pinch/grab strength. It contains no gesture recognition, no cursor control, no CGEventPost. The entire gesture→computer-use layer remains to be built, and adopting this commits that layer to Swift, whereas the already-verified DDlabAU Python path reaches the same 111 fps and sits next to a Python CGEventPost story.


### studiome/leapgo — ADOPT

```
FETCHED AND EXECUTED ON THIS MACHINE (not just read). Clone at /private/tmp/claude-501/-Users-joerup-era-era-memory-evals/1f99f28d-32a3-423c-93b9-1778e24655e6/scratchpad/leapgo; Go 1.26.5 darwin-arm64 toolchain unpacked at .../scratchpad/go (Go was NOT previously installed on this machine).

REPO FACTS (GitHub API, 2026-08-12):
- created_at 2026-07-28T07:13:53Z, pushed_at 2026-07-30T01:05:04Z. Exactly TWO commits: 2161ba59 "Go binding for Ultraleap hand tracking" (2026-07-28) and 26441f6c "Build and run on Linux as well as macOS" (2026-07-30). Author Kazuhiro Miyahara (kmiyahara@studiomexx.org / kazuhiro.miyahara.vs@gmail.com).
- 0 stars, 0 forks, 0 issues (open or closed), NO releases, NO tags. archived=false. MIT + a NOTICE that correctly scopes MIT to the Go source and disclaims libLeapC.
- Size: 2,939 Go LOC non-test, 1,374 test LOC, 409 C LOC (shim). go.mod = `module github.com/studiome/leapgo` / `go 1.24`, ZERO external dependencies (no go.sum).
- Sibling repo studiome/LeapSwift exists (created 2026-07-26, pushed 2026-08-03, 0 stars, MIT) — the "port of LeapSwift by same author" claim is true.

BUILD + TEST ON TARGET HARDWARE:
- `go build ./...` clean in 4.2s with Apple clang 21.0.0.
- `go test ./...` → all 4 packages ok. `go vet ./...` → silent. `go test -race -count=1 ./...` → all ok, including the live cgo poll loop.
- LIVE TESTS ACTUALLY RAN (did not skip) against the ORIGINAL v1 controller: TestLiveDeviceInfo logged `device {Serial:LP20006680004 ... Baseline:37000}`; TestLiveVersions logged client library 6.2.0 / server library 6.2.0, protocol 3.1.0; TestLiveFrames streamed 100 frames, 0 dropped. TestShimLayoutMatches and TestHandFieldMapping pass.
- `cmd/leapdump` built and run for 8s: sustained 110.4–111.7 Hz frame delivery ("frame 181734  110.7 Hz"), matching the ~111 fps you measured through the Python bindings. `file` → "Mach-O 64-bit executable arm64" (native, no Rosetta). `otool -L` → `@rpath/libLeapC.6.dylib` — links the Hyperion v6 SONAME directl
```

**Corrections:** Three corrections, one of them material to your setup:

1. MATERIAL — the README states a hardware requirement that is FALSE on your machine. README lines 56 and 61-63: "A **Leap Motion Controller 2**, the device Hyperion supports" and "Hyperion also does not support the original Leap Motion Controller, for which Gemini v5 remains current." Your ground truth is right and the README is wrong: Hyperion 6.2 re-added v1 support, and I streamed 110.6 Hz off LP20006680004 through leapgo's own live tests and leapdump. The code is device-agnostic (it just polls LeapC), so this is a doc defect, not a functional one — but it means the AUTHOR NEVER TESTED AGAINST A v1 DEVICE. Do not treat upstream as having validated v1 behavior.

2. "auto-locating /Applications/Ultraleap Hand Tracking.app/..." overstates it. There is no search or pkg-config — the macOS paths are hardcoded string literals in the `#cgo darwin CFLAGS/LDFLAGS` directives at leapc/leapc.go:4-5. It works on a stock install and the CGO_CFLAGS/CGO_LDFLAGS override is real (I proved it), but "auto-locating" implies discovery logic that does not exist.

3. "last activity 2026-07-30 (pushed_at)" is accurate but flatters the project. This is a 13-day-old repo with 2 commits, 0 stars, 0 forks, 0 issues, no tags and no releases — `go get` will resolve a v0.0.0 pseudo-version, and there is no release cadence to judge. Calling it "alive" is technically true only because it is brand new; bus factor is 1. The mitigation is that it has zero external dependencies and is ~3.3k lines you can fork outright, so upstream abandonment costs you nothing but maintenance.

Two observations the surveyor did not make, neither disqualifying:
- On the v1 LMC, DeviceInfo returns HorizontalFOV=0, VerticalFOV=0, Range=0 (Baseline=37000 is populated). leapgo copies these verbatim from LeapGetDeviceInfo (shim.c:161-164 → leapc.go:416-419), so this is Hyperion/v1 reporting zeros, not a leapgo bug — but do not build screen-mapping calibration on those fields.
- Real-hand frame content is the one thing I could not verify: TestLiveFrames logged "0 hand observations ... no hands were over the device". Field mapping is covered by TestHandFieldMapping (pushes a C-built hand with distinct values through the real conversion path), so residual risk is low, but wave a hand over the device and check Palm/pinch/grab before committing to it.

Also worth noting for planning: no camera-image or fiducial access is exposed (LeapC's ImageSample/FiducialTracking surface is not wrapped), and there is no gesture recognition — "capture layer" in the survey is exactly right. And Go must be installed first; it was not on this machine.


### DDlabAU/LeapMotion-Python-Hyperion — ADOPT

```
REPO FACTS (GitHub API, fetched 2026-08-12)
- Fork of ultraleap/leapc-python-bindings. Created 2025-10-09T11:48:45Z. pushed_at 2025-10-22T12:36:07Z — that is the real last commit (65078477 "finished guide"). The repo's updated_at 2026-03-11 is a metadata touch, not code. So: ~9.7 months since last commit, not "recent".
- 2 stars, 0 forks, 0 releases, 0 tags, Apache-2.0, single author (Ragdasin), org owner DDlabAU. `has_issues: false` — ISSUES ARE DISABLED. "0 open issues" is therefore not evidence of health; there is no bug channel at all.
- Full commit list: 7 commits ahead of upstream, 0 behind. Six are README/_config.yml/logo. Exactly ONE is code: 097ddedd "update to 6" (2025-10-09).

THE ACTUAL CODE DELTA (GitHub compare 2341c6c3...DDlabAU:main) — 2 lines, both in build scripts:
  leapc-cffi/setup.py:            "Darwin": "libLeapC.5.dylib" -> "libLeapC.6.dylib"
  leapc-cffi/src/scripts/cffi_build.py: os_libraries {"Darwin": ["LeapC.5"]} -> ["LeapC.6"]
Files changed vs upstream: README.md, _config.yml, logo.jpeg, leapc-cffi/setup.py, leapc-cffi/src/scripts/cffi_build.py. `leapc-python-api/` (the `leap` package you actually import) is BYTE-IDENTICAL to upstream.

ON-MACHINE RE-VERIFICATION (run just now, not taken on trust)
- Vendored at /Users/joerup/era/leap-input/vendor/LeapMotion-Python-Hyperion, HEAD 650784771c694d3b014ff25372877fb17f567738 (2025-10-22), remote = the candidate repo.
- /Users/joerup/era/leap-input/.venv/bin/python -c "import leap; leap.get_server_status()" -> {'version': 'v6.2.0-c98d293a', 'devices': [{'serial': 'LP20006680004', 'type': 'LMC'}]}; python 3.12.13, platform.machine() = arm64. Still works today.
- direct_url.json in leap-0.0.1.dist-info confirms editable install from vendor/.../leapc-python-api. leapc_cffi/ in site-packages is a verbatim copy of the SDK's (same sizes: 394368 .so, 7270080 libLeapC.6.dylib).

ARM64 / HYPERION EVIDENCE
- SDK's bundled _leapc_cffi.cpython-312-darwin.so is a universal binary [x86_64 + arm64]; otool -L
```

**Corrections:** 1. "The commit 'update to 6' is the substantive change" — true but materially understated: it is a 2-line string swap in the CFFI *build* scripts only. Nothing in the `leap` API was touched.

2. BIGGEST CORRECTION — the fork contributes essentially nothing to the setup that is actually running on this machine. The working install uses the SDK's PREBUILT leapc_cffi (copied into site-packages) and installs only `leapc-python-api`, which is byte-identical to upstream. The fork's 2-line delta lives in the source-build path (`python -m build leapc-cffi`), which was bypassed. Upstream ultraleap/leapc-python-bindings would have produced the identical working result. Practical consequence: this is not a dependency worth being afraid of losing — if the fork vanishes, `pip install -e leapc-python-api` from upstream plus the SDK's bundled leapc_cffi reproduces it exactly. Treat the fork as "upstream + a README", and keep it vendored/pinned (it already is, at 6507847).

3. "Updated for Hyperion v6" is incomplete, not wrong. The author missed a v5 reference in the file that matters most: leapc-python-api/src/leap/__init__.py still declares _OS_REQUIRED_CFFI_FILES["Darwin"] = ["__init__.py", "libLeapC.5.dylib", "libLeapC.dylib"]. On a Hyperion 6.2 install that check returns False. It is benign — it only selects which error message is printed if the import fails — but it proves the "update to 6" was a shallow grep-and-replace, and it means a real failure here reports the misleading "Missing required files" text.

4. "LEAPSDK_INSTALL_LOCATION override" is an upstream feature (Ultraleap, 2023), not something this fork added. Same for the OS default-path table.

5. "Last activity 2025-10-22" is right, but the repo's GitHub `updated_at: 2026-03-11` is a metadata touch that could be misread as activity. Real code activity: 2025-10-09, one commit. Also note the fork's `.gitlab-ci.yml` is inherited from Ultraleap's GitLab and does not run on GitHub — there is zero CI on this fork.

6. "No open issues" (implied health signal) is false as a signal — issues are disabled on the repo (`has_issues: false`).

7. Verdict caveat: ADOPT is warranted only because it is vendored and re-verified live today, and because the risk is bounded by point 2. On the usual health metrics (2 stars, 1 contributor, no releases, no CI, no issue tracker, ~10 months idle, upstream itself idle since Nov 2023) this would be a REJECT. It survives because the C API underneath is stable and the delta is reconstructible in 2 lines.


### ultraleap/leapc-python-bindings — TRIAL

```
DEAD UPSTREAM — confirmed via GitHub API:
- Last actual code commit: 2341c6c3 "GEM-3480 - Documentation & Type Hinting Improvements", authored AND committed 2023-11-17T13:35:01Z. Single branch (main). `pushed_at` 2024-06-24 is PR #7's branch push, not main.
- ZERO releases and ZERO tags ever (`/releases` and `/tags` both return `[]`). Not on PyPI — `pypi.org/pypi/leapc*` all 404; the PyPI name `leap` is Andreas Kloeckner's unrelated time-integration library (v2021.1). Source-install only.
- 3 PRs open and unmerged for 2-4 years (#4 2023-12-29, #7 2024-06-24, #9 2024-09-12). Last maintainer (RodolpheHoudas-UL) comment anywhere: 2024-04-09. Issue #16 (2025-12-12) and #14 (2025-04-16) have no maintainer reply; #16's only response is another user asking "What python version are you using?" (2026-02-17). Description still reads "Gemini LeapC Python Bindings"; README still says "Gemini" throughout. No successor exists in the ultraleap org (repo listing sorted by push shows nothing Python/LeapC newer).

THE HYPERION BREAKAGE IS REAL BUT NARROWER THAN CLAIMED — three hardcoded `.5` references, all macOS-only:
- `leapc-cffi/setup.py:40` — `"Darwin": "libLeapC.5.dylib"` (symlink source, hard-fails)
- `leapc-cffi/src/scripts/cffi_build.py:95` — `"Darwin": ["LeapC.5"]` (linker `-lLeapC.5`)
- `leapc-python-api/src/leap/__init__.py:21` — `"Darwin": [..., "libLeapC.5.dylib", ...]` (soft — only changes an error message)
This machine's SDK ships only `libLeapC.6.dylib` + a symlink `libLeapC.dylib`; no `.5` exists anywhere under the app bundle.

MEASURED ON THIS MACHINE (uv venv, Python 3.12.13, scratchpad, upstream at 2341c6c3 unmodified):
- TEST B (README "Missing Compiled Module" source-build path): `python -m build leapc-cffi` → `Exception: No libLeapC.5.dylib found, please ensure you have Ultraleap Gemini Hand Tracking installed` (raised at setup.py:69 via gather_leap_sdk → setup_symlink). CONFIRMED BROKEN.
- TEST A (README default prebuilt path): `pip install -e leapc-python-ap
```

**Corrections:** Four corrections:

1. "macOS viability: no (as-is with Hyperion)" — WRONG, and this is the load-bearing error. Upstream at 2341c6c3, unmodified, imports and streams tracking at 112 fps against Hyperion 6.2 on this exact machine. The surveyor generalized the DDlabAU fork's README ("it was outdated so it didn't work for macOS with the hyperion software") into a blanket failure. That statement is true only of the CFFI *source-build* path. The `leapc-python-api` half — which is 100% of the actual API surface, and byte-identical in the fork — has zero Hyperion incompatibility.

2. "prebuilt CFFI modules are documented for Python 3.8 only" — the README does say that ("Darwin: Python 3.8"), but the README is stale, not just the claim. It describes the Gemini 5.17 release. Hyperion 6.2 ships `_leapc_cffi.cpython-312-darwin.so` and ONLY that. The operative constraint is Python 3.12 exactly — neither 3.8 nor the system 3.14.6.

3. "This is the upstream that every fork descends from" — accurate, but implies the forks carry meaningful improvements. DDlabAU's entire code delta is two string literals in the build scripts. Do not treat the fork as a maintained successor; it is a 2-line patch with a rewritten README.

4. Dates — CONFIRMED and worth tightening: last code commit 2023-11-17 (correct), pushed_at 2024-06-24 (correct, and it is PR #7's branch, not main). Add: never tagged, never released, never published to PyPI. `updated_at` 2026-07-10 is metadata churn only.

RECOMMENDATION: use it, but vendor it. Copy `leapc-python-api/src/leap/` into the project (Apache-2.0, ~1200 LOC, no runtime deps beyond cffi), pin the venv to 3.12, and preemptively apply the `.5`→`.6` patch to setup.py:40 and cffi_build.py:95 so the rebuild escape hatch exists before you need it. Do not add a git dependency on a repo with no tags and a dead maintainer.


### ultraleap/TouchFree — REJECT

```
FETCHED AND INSPECTED (gh api + raw.githubusercontent, 2026-08-12).

Repo metadata (gh api repos/ultraleap/TouchFree): archived=true, disabled=false, fork=false, created 2020-10-12, pushed_at 2023-04-21T14:52:59Z, default_branch "develop", language C#, license Apache-2.0, 28 stars, open_issues_count 0, size 104MB.

Last commit on develop: 7452704d 2023-04-21T14:35:58Z "Merge pull request #494 from ultraleap/feat/TF-1247_archive-github-repo" — the final commit is literally the ticket to archive the repo. Preceding commits same day: "Update readme badges", "Update readme". Archiving was deliberate and self-documented.

Releases: GitHub Releases list is EMPTY. Only git tags exist; newest product tag is release/App_And_Service/2.6.0 (changelog dates 2.6.0 to 2022-03-20). Also release/Tooling_for_Web/1.4.0, release/Service-Brightsign/2.5.0-beta. The [Unreleased] changelog section never shipped from this repo.

README at develop HEAD: "## Notice — **Content for this repository has moved**" pointing to developer.leapmotion.com/touchfree (binary installer only) and the two tooling repos. The App+Service went closed-source; only the installer is distributed.

macOS: ZERO evidence of any macOS path, ever. Recursive tree of develop = 1084 paths; grep -iE 'macos|osx|darwin|dylib' returns 0 hits. The only native tracking binaries shipped are TF_Service_dotNet/TouchFree/Plugins/LeapC/AnyCPU/LeapC.dll (Windows) and Plugins/LeapC/ARM64/libLeapC.so.5 + libstdc++.so.6.0.28 + libatomic.so.1.2.0 (Linux ARM64, BrightSign). No .dylib, no darwin RID.

OS-input injection — the decisive finding. TF_Application/Assets/Scripts/Input/TouchController.cs is the ONLY code in the repo that produces operating-system input, and it is a hardcoded Windows P/Invoke with no abstraction layer:
  [DllImport("User32.dll")] internal static extern bool InitializeTouchInjection(uint maxCount, TouchFeedback feedbackMode);
  [DllImport("User32.dll", SetLastError = true)] internal static extern bool InjectTouchI
```

**Corrections:** Four corrections, one of them material to how this candidate should be weighted.

1. MATERIAL — "end-to-end" and "exactly the product this project is trying to rebuild" is wrong. TouchFree is NOT end-to-end. The Service (the cross-platform, reusable part) emits only WebSocket InputAction messages (position + NONE/MOVE/DOWN/UP, API version 1.4.0) to web/Unity clients; it injects nothing into the OS. OS input exists in exactly one place — the Windows Unity Overlay app calling User32 InjectTouchInput. And what it injects is touchscreen contacts, not the target feature set: there is no scroll, no keyboard/shortcut synthesis, no app control, no multi-gesture vocabulary beyond one pointer with press/release. Even a hypothetical macOS port would deliver roughly "cursor + click" and stop. Treat this as a reference for gesture-to-2D-pointer math, not as a missing implementation of the goal.

2. "Windows Service architecture" overstates the lock-in. The service is net6.0 with RuntimeIdentifiers win-x64;linux-arm64;linux-x64, ships a BrightSign/RPi ARM64 Linux build with libLeapC.so.5, has a BRIGHTSIGN compile constant, a CHANGELOG-brightsign.md, and PR #484 "[TF-1304] Build for RPi". The service was already multi-platform — it just never targeted Darwin. The Windows-only pieces are the installer, the tray app, and the injection layer. This does not change the verdict but the surveyor's stated reason is not the real blocker.

3. "no macOS code path ever existed" — CONFIRMED, and stronger than claimed: 0/1084 tracked paths match macos|osx|darwin|dylib.

4. Archive dates — consistent but not directly provable. The GitHub API does not expose archived_at. TouchFree: pushed_at 2023-04-21 with the final commit being the archive ticket, so 2023-04-21 is right. TouchFree-Current: the surveyor's 2023-05-23 matches updated_at, but its last actual code push was 2021-05-10 — it had been dead two years before archival.

5. Omitted by the surveyor: the repo was gutted at HEAD ("Content for this repository has moved") and the App+Service became closed-source binary-only. The live-looking successors (TouchFreeWebTooling, unarchived, TypeScript) are client-side only and are themselves dormant since Nov 2023 with an unmerged 2.0.0 release PR — do not mistake the unarchived flag for maintenance.

6. Omitted: the bundled LeapC binding is v5/Gemini (libLeapC.so.5), so even the harvestable code is one SDK major behind the machine's libLeapC.6.dylib.


## Lens: generic-gesture-to-input

The "control your computer with hand gestures" category is ~95% student coursework: MediaPipe Hands → a few if-statements → `pyautogui`, abandoned within a semester. After filtering on real commit activity (checked per-path, not by `pushed_at`), only two credible end-to-end systems remain: **Gstrl** (macOS-native Swift, Vision → CGEvent, MIT, actively built May 2026) and **Heliox-OS** (Tauri/Svelte + Python daemon, MIT, commits the day of this survey). The single most important negative finding is that **Google's MediaPipe Gesture Recognizer task is image-in only** — it cannot be fed precomputed landmarks, so the obvious "keep Google's gesture layer, swap the camera for a Leap" plan is impossible with the shipped API; only landmark-in MLPs (Kazuhito00, PINTO0309) and geometric matchers (HandVector, fingerpose) are truly separable. The second is that **PyAutoGUI — the action layer under nearly every project in this space — has been dead since May 2023 and is quietly broken on macOS**: its `_multiClick` never sets `kCGMouseEventClickState`, so `doubleClick()` posts two independent single clicks that Finder and text views do not read as a double-click. `pynput` sets that field correctly and is actively maintained, making it the only defensible cross-platform shim. For this project the highest-value artifacts are not whole apps but two files and one socket: Gstrl's `InputDispatch.swift` (a clean, Vision-free CGEvent action layer), Gstrl's `AgentController.swift` (already pipes gestures into the Claude Code CLI), and Heliox's JSON-RPC daemon at `ws://127.0.0.1:8785` exposing 156 guarded action types that a Leap process could drive directly, bypassing its webcam gesture layer entirely.

| Candidate | Layer | Verdict | Last activity |
|---|---|---|---|
| [Gstrl](https://github.com/TomYang-TZ/Gstrl) | end-to-end | **TRIAL** | 2026-05-20 (last commit on master, verified via API); repo created 2026-05-07; 191 commits; no tagged releases |
| [Heliox-OS](https://github.com/VyomKulshrestha/Heliox-OS) | orchestration | **—** | 2026-08-12 — commits landed the day of this survey; 731 commits; v0.11.1; created 2026-03-06 |
| [pynput](https://github.com/moses-palmer/pynput) | action-injection | **ADOPT** | 2026-05-12 (v1.8.2 on PyPI and last repo push, same day) |
| [PyAutoGUI](https://github.com/asweigart/pyautogui) | action-injection | **TRIAL** | DEAD — last PyPI release 0.9.54 on 2023-05-24; last repo push 2024-08-20. Nearly three years without a release. |
| [Hammerspoon](https://github.com/Hammerspoon/hammerspoon) | action-injection | **ADOPT** | 2026-07-08 last push; stable v1.1.1 released 2026-02-26 |
| [PINTO0309/hand-gesture-recognition-using-onnx](https://github.com/PINTO0309/hand-gesture-recognition-using-onnx) | gesture-recognition | **—** | 2026-01-06 (last push); 91 stars; Apache-2.0 |
| [Kazuhito00/hand-gesture-recognition-using-mediapipe](https://github.com/Kazuhito00/hand-gesture-recognition-using-mediapipe) | gesture-recognition | **—** | STALE — last push 2023-04-05, over three years ago; 753 stars, 682 forks, Apache-2.0 |
| [MediaPipe Gesture Recognizer (google-ai-edge/mediapipe)](https://github.com/google-ai-edge/mediapipe) | gesture-recognition | **—** | 2026-08-12 (parent repo pushed the day of this survey); 36.6k stars; Apache-2.0; docs page updated 2026-05-28 |
| [XanderXu/HandVector](https://github.com/XanderXu/HandVector) | gesture-recognition | **—** | 2026-02-09 (v2.2.0); 200 stars; MIT; consistent release cadence (2.1.1 in Oct 2025) |
| [pqrs-org/Karabiner-DriverKit-VirtualHIDDevice](https://github.com/pqrs-org/Karabiner-DriverKit-VirtualHIDDevice) | action-injection | **—** | 2026-08-09 (three days before this survey); 365 stars; Unlicense (public domain) |
| [ultraleap/UnityPlugin](https://github.com/ultraleap/UnityPlugin) | gesture-recognition | **—** | 2026-07-07 last push; release com.ultraleap.tracking/7.3.0 on 2026-02-25; 589 stars; Apache-2.0 |
| [andypotato/fingerpose](https://github.com/andypotato/fingerpose) | gesture-recognition | **—** | STALE — last push 2023-05-01; 509 stars; MIT |
| [NonMouse](https://github.com/takeyamayuki/NonMouse) | end-to-end | **—** | MISLEADING — repo `pushed_at` is 2026-08-10, but the Python core last changed 2023-05-08. Latest release v2.7.0, 2023-05-08. 198 stars, Apache-2.0. |
| [Viral-Doshi/Gesture-Controlled-Virtual-Mouse](https://github.com/Viral-Doshi/Gesture-Controlled-Virtual-Mouse) | end-to-end | **—** | STALE — last push 2023-11-13; 844 stars; GPL-3.0 |
| [BlueM/cliclick](https://github.com/BlueM/cliclick) | action-injection | **—** | 2025-08-23 last push; 2.0k stars; license NOASSERTION (custom, permissive in practice — verify before distribution) |
| [noah-nuebling/mac-mouse-fix](https://github.com/noah-nuebling/mac-mouse-fix) | action-injection | **—** | 2026-08-12 (the day of this survey); 10.7k stars; license NOASSERTION (source-available, commercial product) |
| [google/project-gameface](https://github.com/google/project-gameface) | end-to-end | **—** | ARCHIVED — read-only since 2024-08-30; 634 stars; Apache-2.0 |

### Gstrl — TRIAL

```
REPO IS REAL AND THE DATES CHECK OUT. Cloned https://github.com/TomYang-TZ/Gstrl to scratchpad. GitHub API: created_at 2026-05-07T22:02:42Z, pushed_at 2026-05-20T14:57:05Z, MIT, Swift, 6 stars, 1 fork, 1 open issue, not archived. `git rev-list --count HEAD` = 191 commits exactly. HEAD = c946814e852c2aeb1e50a3572f2663fd9ae00ac3, 2026-05-20 07:57:03 -0700, "fix cursor navigation on built-in display". `git tag` empty, /releases API returns []. Surveyor's dates/counts are all exactly right. NOTE: repo updated_at is 2026-08-04 but that is metadata (star/description), not code — pushed_at 2026-05-20 is the real last activity, ~3 months dormant as of today 2026-08-12.

IT BUILDS CLEAN ON THIS EXACT MACHINE — the decisive test. `swift build` with the toolchain already here (Apple Swift 6.3.3, target arm64-apple-macosx26.0, SDK 26.5, CommandLineTools only — no full Xcode installed): "Build complete! (41.36s)", zero errors, zero warnings surfaced. `file` on the product: "Mach-O 64-bit executable arm64". `make build` then assembled Gstrl.app successfully. `otool -L` confirms it links Vision.framework, AVFoundation, CoreGraphics, Speech.framework — the exact claimed stack. This is not a stale-2014-content candidate; it is a working 2026 codebase that compiles today.

CLAIMED ARCHITECTURE VERIFIED IN SOURCE. 5,173 LOC Swift across 21 files. TrackingCoordinator.swift:255 `VNDetectHumanHandPoseRequest()` with `maximumHandCount = 2`. CameraManager.swift AVCaptureSession delivering CVPixelBuffer. InputDispatch.swift builds CGEvent keyboard/mouse events via `CGEventSource(stateID: .privateState)` and posts to `.cghidEventTap` — real synthetic-event injection, which the ground truth confirms is already permissioned here. SpeechEngine.swift uses SFSpeechRecognizer. AgentController.swift:297-318 spawns a real Process against the Claude Code CLI with sensible path fallbacks (`~/.local/bin/claude`, `/usr/local/bin/claude`, `/opt/homebrew/bin/claude`, `~/.claude/local/claude`) using `-p` s
```

**Corrections:** Four corrections, one of them material.

1. MATERIAL — "12 remappable gesture slots (pinch-cursor, pinch+fist scroll, open-palm swipe→arrows, dual-pinch drag, shaka→delete, dual-fist→ask Claude)". The COUNT of 12 is correct, but the enumerated examples are wrong and the surveyor conflated the marketing feature list with the remappable slot list. The actual `GestureSlot` enum (KeyBinding.swift:21-32) is: leftFist, leftThumbPinky, leftOpenPalm, leftOneFinger, leftTwoFingers, leftThreeFingers, swipeLeft, swipeRight, swipeUp, swipeDown, swipeLeftWithLeftOpen, swipeRightWithLeftOpen — i.e. 6 left-hand HOLD poses + 4 right-hand swipes + 2 left-open+swipe combos. Of the six features the surveyor named as slots, only "open-palm swipe→arrows" is actually remappable. Pinch-to-move-cursor, pinch+fist scroll, dual-pinch drag-and-drop, dual-fist→ask-Claude, circle→screenshot, and the right-hand shaka→delete escalation are ALL HARDCODED behaviors with no rebinding UI. Also note shaka/six is bound differently per hand: LEFT six defaults to Escape (and is remappable), RIGHT six is the hardcoded delete escalation — the surveyor's "shaka→delete" points at the non-remappable one.

2. "macOS-native menu-bar app" — imprecise. It does create an NSStatusItem (GstrlApp.swift:160-169), but Info.plist sets `LSUIElement` to `<false/>`, so it is a normal Dock/windowed app that ALSO has a status item, not a menu-bar-only agent. This is not pedantry: open issue #2 is a user reporting exactly this confusion ("the close button does not quit, and I don't see a tray icon"), unanswered since 2026-05-18.

3. "Claimed layer: end-to-end" — true only for the webcam path. Understate-to-overstate risk: this is end-to-end for a DIFFERENT sensor than the one already verified working on this machine. It contributes zero to the Leap integration and, if adopted as-is, makes the verified Hyperion 6.2 + 3.12-venv work irrelevant. Worth stating plainly rather than filing it under "end-to-end, viability yes".

4. Minor/additive, not contradictions: the surveyor's "no tagged releases" is right but undersells the hygiene gap — there is also no CI, no tests, an ad-hoc-only signature, a stale project.yml still referencing the pre-rename "iGest" paths, and `make install` shipping a debug build. Also an internal doc contradiction: HANDOFF.md says "AVCaptureSession @ 30fps" while README says 60 default / up to 120; the code (AppState.swift:105-115) offers 60/120, so HANDOFF.md is the stale one.

Everything else the surveyor claimed — 2026-05-20 last commit, 2026-05-07 creation, 191 commits, no releases, Swift 5.9+/macOS 14+, macOS 26+ Liquid Glass with documented graceful fallback, AVCaptureSession→VNDetectHumanHandPoseRequest→geometric classifier→CGEvent, SFSpeechRecognizer dictation, and the Claude Code CLI agent controller — is accurate as stated and independently verified above.


### Heliox-OS (VyomKulshrestha/Heliox-OS) — REJECT

```
LIVENESS — the surveyor's activity claims are TRUE and verified. GitHub API: created 2026-03-06T22:11:16Z, pushed_at 2026-08-12T20:30:24Z (commits landed the day of the survey — top commit cdf5136 "fix(ci): make release feeds timezone deterministic" at 20:30:11Z). Commit count via Link-header last page = exactly 731. Latest release v0.11.1 published 2026-08-12T18:07:15Z. 62 stars, 106 forks, MIT, not archived. 10 releases since March, cadence steady. Real substance, not vaporware: 216 Python files / 73,307 LOC in daemon/pilot, 186 test files, 1,997 LOC Rust, enigo 0.6 for genuine input actuation. capabilities.json contains exactly 156 actions — the "156 guarded action types" claim is literally true.

DECISIVE FINDING — ZERO LEAP SUPPORT. `grep -rin "leapc|leap motion|leapmotion|ultraleap|libLeapC"` across the entire 56MB clone returns ZERO hits. Every case-insensitive "leap" match in the repo is the substring inside `googleapis.com` (e.g. daemon/pilot/system/gesture.py:162 `storage.googleapis.com/mediapipe-models/...`, requirements-lock.txt `googleapis-common-protos`). Gesture input is exclusively MediaPipe Hands over webcam: `hand_landmarker.task` (MediaPipe model) sits at repo root; daemon/pyproject.toml pins `mediapipe>=0.10.11`; requirements-lock.txt pins mediapipe==0.10.35. GESTURES.md line 3 states verbatim: "webcam-based hand gesture recognition engine powered by MediaPipe Hands." The "30+ gestures" v3 engine lives in the UI TypeScript layer (tauri-app/ui/src/lib/gesture/spatialModel.ts, temporalGestureVerifier.ts) — browser-side MediaPipe in the Tauri webview. A separate, older 12-gesture MediaPipe stub sits in daemon/pilot/system/gesture.py. Heliox's gesture layer is a COMPETITOR to Leap input, not a consumer of it. Nothing about libLeapC.6 / Hyperion 6.2 / the LMC v1 is addressed anywhere.

CONFIRMED macOS BLOCKER IN HEAD (not in any open issue — found by reading code). The Python daemon writes its auth token to `RUNTIME_DIR / "auth_token"` (daemon/pilot/s
```

**Corrections:** Four corrections, one of them decisive.

1. DECISIVE — the surveyor listed "30+ gestures" without disclosing that they are WEBCAM/MediaPipe gestures with zero Leap Motion support of any kind. This is the single fact that determines the verdict, and the survey omits it entirely. Heliox has no LeapC binding, no libLeapC linkage, no Ultraleap awareness. For a Leap-based project it is not an orchestration layer that accepts our input — its gesture subsystem is a parallel, webcam-coupled implementation of the same job, living in the Tauri UI's TypeScript.

2. "macOS viability: yes, but caveated" is too generous. The correct statement is that macOS arm64 packages genuinely build and ship, but the packaged app is BROKEN AT HEAD: Rust get_auth_token() has no darwin path, so the UI cannot authenticate to its daemon on macOS. The survey caveat ("permissions/hardware require local validation") repeats the README's own hedge rather than reporting the actual defect. Also unreported: no Apple codesigning or notarization.

3. Unstated architectural caveat: the documented gesture/cursor RPC seam is self-described as a degraded dev-mode fallback that cannot sustain ~30fps, whereas our verified Leap stream is ~111fps. The high-rate path is in-process Rust/enigo and is not reachable from an external process.

4. Context the survey omits: this is a GSSoC '26 summer-of-code repo (branding removed from the README the same day as the survey), which explains the 731-commit/106-fork velocity, and it carries open unfixed shell-injection (#425) and path-traversal (#328) issues in software whose purpose is executing privileged system actions.

Everything the surveyor asserted numerically is accurate and I confirmed it: 731 commits, v0.11.1, created 2026-03-06, commits on 2026-08-12, 156 action types (exactly, in capabilities.json), Tauri/Svelte + Python daemon, pluggable LLM providers, and the README's "Windows is the primary hardware-development platform" line (README:38).

Verdict rationale: REJECT for this project's stated goal (Leap Motion → macOS computer-use). Not abandoned and not vaporware — rejected because the load-bearing requirement, Leap integration, is wholly absent, the macOS path is broken at the auth layer today, and the exposed integration seam is explicitly too slow for our data rate. Adopting 73k LOC with open injection vulnerabilities to obtain a gesture-to-action mapper we could write in ~200 lines against CGEventPost (already permission-granted on this machine) is poor value. This would flip to TRIAL only if the goal changed to "adopt a general local-first agent orchestration platform," in which case the ~5-line darwin fix to get_auth_token() would be the first patch to send upstream. The one idea worth stealing regardless is the design of its JSON-RPC seam: a local WebSocket accepting {gesture, confidence, data} events into a fusion engine behind permission/risk gates.


### pynput — ADOPT

```
LIVENESS (GitHub API + PyPI JSON, fetched 2026-08-12):
- Last commit afc64577 "Release 1.8.2" at 2026-05-12T19:11:32Z; repo pushed_at identical. Tag v1.8.2 = afc64577. archived=false, disabled=false, LGPL-3.0, 2165 stars / 286 forks, default branch master.
- PyPI pynput 1.8.2 uploaded 2026-05-12T19:11:37 (wheel + sdist). Surveyor's "2026-05-12, same day" claim is exactly correct.
- Cadence is bursty/single-maintainer: commits per year 2021=55, 2022=16, 2023=11, 2024=4, 2025=25, 2026=9 (all on one May day). Zero commits in the ~3 months since. Release gap 1.8.1 (2025-03-17) -> 1.8.2 (2026-05-12) = 14 months.
- Backlog growing: 200 open issues, 32 open PRs; 21 issues opened vs 14 closed in trailing 12 months. Unmerged macOS PRs: #684 "Invalidate the macOS event tap on listener stop" (2026-07-28), #655 "Fix: 'injected' argument missing in keyboard/_darwin.py" (2025-06-14).

CLAIM VERIFICATION (source read from installed 1.8.2):
- mouse/_darwin.py:85-86, 94-95, 118, 135 -> Quartz.CGEventPost(Quartz.kCGHIDEventTap, ...)
- keyboard/_darwin.py:37, 46, 227-228 -> CGEventPost(kCGHIDEventTap, ...)
- _util/darwin.py:272-277 -> CGEventTapCreate(kCGSessionEventTap, kCGHeadInsertEventTap, ...) for listeners.
Claim "wraps Quartz CGEvent directly, posts to kCGHIDEventTap" is accurate verbatim. Injection at HID tap, listening at Session tap.

ON-MACHINE FUNCTIONAL VERIFICATION (arm64, this MacBook Pro):
- uv venv CPython 3.12.13, arm64. `uv pip install pynput` -> pynput==1.8.2 + pyobjc-core/cocoa/quartz/applicationservices/coretext 12.2.2 + six. Pure Python over pyobjc; no compiled pynput extension. CRITICAL FIT: works under the CPython 3.12 pin forced by the SDK's bundled leapc_cffi.
- Absolute positioning exact: 8/8 targets matched an independent Quartz.CGEventGetLocation readback exactly, including second-display negative coords (-500,-1400), (1000,-800), (1900,-100). pynput's own position getter also matched truth on every sample.
- Round trip Controller -> Listener: move(81), s
```

**Corrections:** 1. GROUND TRUTH IS INCOMPLETE ON DISPLAYS. The task states "Main screen 1512x982 logical points" (singular). The machine has TWO active displays: id 1 = 1512x982 at origin (0,0) (main, built-in Liquid Retina XDR), and id 2 = 2560x1440 at origin (-541,-1440) (5120x2880 panel, UI-scaled to 2560x1440). The global Quartz coordinate space therefore spans negative x AND negative y. pynput handles this correctly (verified at negative coords), but any gesture->screen mapping written against a 0..1512 x 0..982 box will strand the pointer or make the second display unreachable. Multi-display mapping must be an explicit design input.

2. SURVEYOR'S "last activity 2026-05-12" IS TRUE BUT FLATTERING. It implies ongoing maintenance; in reality that date is a single burst day (9 commits, all 2026-05-12) with zero commits in the ~3 months since, preceded by a 14-month release gap. The project is alive but low-bandwidth and single-maintainer, with a growing backlog (200 issues / 32 PRs open; opens outpacing closes 21:14 over 12 months). Not abandoned — but do not assume a bug report gets fixed upstream on any useful timescale.

3. SURVEYOR OMITTED TWO REAL FUNCTIONAL LIMITS, both measured here: injected moves carry zero mouse-delta fields, and fractional scroll is silently truncated to a no-op with a 10px minimum step. Neither is disqualifying, but both are directly load-bearing for a gesture-driven cursor and both require dropping to raw Quartz for those two specific calls.

4. "Requires Accessibility permission" — confirmed correct and already satisfied. Related open issue #634 ("MacOS silent failure on Controller") is NOT a code defect as its title suggests; it is a diagnostics gap (Controller fails silently when permission is missing, whereas Listener warns). It does not apply here since permission is granted.

5. Leap-specific verification questions (libLeapC.6 / Hyperion v6 compatibility) are NOT APPLICABLE to this candidate — pynput has no Leap dependency whatsoever. It is a pure action-injection layer, cleanly separated from capture. Confirmed no import or native conflict with the working Leap 3.12 stack.

6. Minor: PyPI classifiers advertise Python only through 3.9 and there is no requires_python bound — stale metadata, not a real constraint. Verified working on 3.12.13.


### PyAutoGUI — TRIAL

```
Not Leap-specific, so libLeapC.6/Hyperion compatibility is a non-question. Verified ON-MACHINE (macOS 26.5, arm64, Python 3.12 venv). Scripts kept at /private/tmp/claude-501/-Users-joerup-era-era-memory-evals/1f99f28d-32a3-423c-93b9-1778e24655e6/scratchpad/pag_test.py and pag_test2.py; venv at .../scratchpad/pagvenv.

LIVENESS (hard data)
- PyPI: latest 0.9.54, uploaded 2023-05-24T20:11:32. Not yanked. Confirms surveyor.
- GitHub: repo has exactly ONE branch (master), last commit 2023-06-07T11:16:23 ("Adding Zander Møysal to AUTHORS list"). Last functional macOS commit 2023-05-09 "Fix mouse swap detection on macOS." Repo has NO tags. Not archived.
- 507 open issues, 76 open PRs; oldest open PR is #147-era dated 2016-09-19, newest 2026-07-25. Six unmerged macOS PRs incl. #949 "Fix macOS multi-click by setting CGEvent click state" (2026-01-31) and #947 "Fix macOS keyboard layout issues with Unicode typing" (2025-12-22).
- Issue #630 "Come up with a fix for screenshots at different scales" is a maintainer note-to-self opened 2021-10-03, STILL OPEN 5 years later.

INSTALL / ARM64 — WORKS
uv pip install pyautogui on Python 3.12.13 arm64 resolved cleanly: pyautogui 0.9.54, pyobjc-core/cocoa/quartz 12.2.2 (released 2026-08-11, i.e. current), pyscreeze 1.0.1, rubicon-objc 0.5.6. No build errors, no x86_64 arch faults. Issue #726 (arm64 incompatible architecture) and #772 (M1 symbol not found) do NOT reproduce.

FUNCTIONAL — CORE ACTION INJECTION WORKS
moveTo landed pixel-exact on every target: (200,200), (1000,700), (1511,981), (760,490) all OK. mouseDown/mouseUp, scroll, and hotkey all posted without error. Float coords truncate cleanly (400.7,300.3 -> 400,300 via _normalizeXYArgs). Issue #834 "moveTo() doesn't work on macOS Sonoma" does NOT reproduce on macOS 26.5.

THE DISQUALIFIER THE SURVEYOR MISSED — 13 ms LATENCY FLOOR
_pyautogui_osx._moveTo is literally:
    _sendMouseEvent(Quartz.kCGEventMouseMoved, x, y, 0)
    time.sleep(pyautogui.DARWIN_CATCH_UP_TIME)   # DARWIN
```

**Corrections:** Five corrections.

1. "last repo push 2024-08-20" — MISLEADING. That is GitHub's `pushed_at` field, which moves for non-commit events. The last actual commit to master (the only branch; no other branches, no tags) is 2023-06-07. The code is 3y2m stale, not ~2y. Note 2024-08-20 is the same day asweigart released pyscreeze 1.0.1, a sibling package.

2. "DEAD" / "no maintainer to fix it" — WRONG AS STATED, and the distinction matters. asweigart is highly active on GitHub: 15+ other repos pushed in July-August 2026 (dice, promptdump, mars-globe, binrg, etc., most recent 2026-08-06). He commented on pyautogui issue #870 on 2026-01-21: apologized for the PR backlog, said he has "been severely burned before by accepting PRs without doing thorough testing," stated a 2026 resolution "to create a community around PyAutoGUI to steward changes," and noted "PyAutoGUI is going to be featured in my next book." Accurate framing: UNMAINTAINED IN PRACTICE (no code commit in 3+ years, 76 open PRs, 507 open issues) but NOT abandoned by a vanished author. A community fork is under active discussion in that thread (KavyanshKhaitan2's fork, incl. talk of PyPI name transfer).

3. "practically no [macOS viability]" — TOO HARSH for the general case. Core action injection is correct and pixel-accurate on macOS 26.5 arm64 with current pyobjc 12.2.2. moveTo, mouseDown/Up, scroll, and hotkey all work. The reject-worthy problem is not "it doesn't work," it's latency and two specific bugs.

4. "a silent correctness bug" (singular, unnamed) — the surveyor was directionally right but did not identify it. There are TWO, both now confirmed: (a) kCGMouseEventClickState is never set, so doubleClick is not a real double-click; (b) the Retina 2x point-vs-pixel mismatch breaking locateOnScreen. Only (b) is arguably "known"; (a) I confirmed from source and by reading the field back.

5. MOST IMPORTANT OMISSION: the surveyor never mentions the hardcoded `time.sleep(DARWIN_CATCH_UP_TIME)` (0.01 s) inside _moveTo, which caps cursor updates at ~76-83 Hz — slower than the Leap's measured 111 fps. For a gesture-to-cursor system this, not the correctness bug, is the decisive fact.

UNVERIFIED: the claim that Heliox-OS and "the overwhelming majority" of webcam gesture-mouse projects use PyAutoGUI as their action layer. I did not check that and it should not be relied on.

RECOMMENDATION (why TRIAL, not ADOPT or REJECT): do NOT use PyAutoGUI for cursor motion — replace that hot path with ~40 lines of direct Quartz CGEventCreateMouseEvent/CGEventPost, which measured 630x faster and lets you set clickState correctly for double-clicks. PyAutoGUI remains worth keeping ONLY for discrete, low-rate actions where 13 ms is irrelevant: its `keyboardMapping` table, `write()`, and `hotkey()` are genuinely tedious to reimplement. If adopted even in that reduced role, pin it, set FAILSAFE=False and PAUSE=0 explicitly, never use size() as a bound on a multi-display setup, and never use locateOnScreen/screenshot (use ScreenCaptureKit or CGDisplayCreateImage instead if the computer-use agent loop needs frames).


### Hammerspoon — ADOPT

```
FETCHED LIVE 2026-08-12 via GitHub API + downloaded the actual 1.1.1 release binary.

REPO STATE (gh api repos/Hammerspoon/hammerspoon): archived=false, disabled=false, pushed_at=2026-07-08T21:13:24Z, created 2014-10-08, 15,919 stars, MIT, Objective-C, default branch master, 681 open issues, 21 open PRs. Surveyor's dates are exactly right.

RELEASES: 1.1.1 published 2026-02-26T10:52:34Z (218,632 downloads), 1.1.0 2025-12-24, 1.0.0 2024-08-06. Not prerelease. Surveyor's "stable v1.1.1 released 2026-02-26" confirmed to the day.

ARM64 — verified on the real artifact, not claimed. Downloaded Hammerspoon-1.1.1.zip (9.7MB) and ran `lipo -info`: "Mach-O universal binary with 2 architectures: [x86_64] [arm64]". LSMinimumSystemVersion=13.0, so macOS 26.5.2 is in range.

GATEKEEPER: `codesign -dv` → Authority=Developer ID Application: Chris Jones (VQCYSNZB89), flags=0x10000(runtime) hardened, Timestamp Feb 26 2026. `spctl -a -vv -t exec` → "accepted, source=Notarized Developer ID". Installs clean on macOS 26 with no quarantine fight.

API SURFACE — every claimed module verified present in source and in the shipped bundle. extensions/ listing includes eventtap, window, application, hotkey, urlevent, ipc, screen, spaces, mouse, axuielement, socket, httpserver, task, hid, timer. In libeventtap_event.m the registered Lua functions include {"post", eventtap_event_post}, {"_newMouseEvent"}, {"newScrollEvent"}, {"newKeyEvent"}, {"newSystemKeyEvent"}, {"newGesture"}, {"setProperty"}. In libeventtap.m: eventtap_new with a documented {"all"} intercept mode, plus start/stop/isEnabled. So both halves of the claim — CGEvent post AND intercept — are real. Bundle ships Contents/Frameworks/hs/libipc.dylib and extensions/hs/ipc.lua.

LEAP RELEVANCE: `search/code repo:Hammerspoon/hammerspoon leapmotion OR LeapC` → total_count 0. Hammerspoon has zero Leap awareness, so the libLeapC.6 / Hyperion v6 question is N/A — it is a pure output-side component, exactly as the surveyor's "action-injection
```

**Corrections:** Surveyor's factual claims all hold — dates, macOS-only, Objective-C, module surface, arm64 viability. Four corrections/additions:

1. "Mature" overstates current velocity. This is maintenance mode, not active development: one commit in the ~5 months since the Feb 2026 release, effectively one maintainer, 681 open issues and PRs sitting since 2021. That does not undercut ADOPT — the CGEvent surface is stable API against stable OS primitives and does not need churn — but do not expect an upstream fix for anything you hit. Budget for carrying local patches.

2. Materially missed gotcha, and it lands squarely on the primary use case: do NOT drive the Leap cursor with hs.mouse.absolutePosition. It calls CGWarpMouseCursorPosition (libmouse.m:111), which suppresses real local mouse/trackpad events for ~250ms per call. At the measured 111fps Leap frame rate that call is continuously re-armed and the physical trackpad goes dead. It is the API you would naively reach for and it is the wrong one. Use the eventtap path instead — hs.eventtap.event.newMouseEvent(hs.eventtap.event.types.mouseMoved, point):post() — which posts a synthetic move without warping and without arming the suppression interval, preserving hand-off between Leap and trackpad. Issue #3332, open 3.5 years, unfixed in master, with a known 4-line fix.

3. "Directly usable" needs an architecture caveat the survey does not address. The verified Leap stack is Python 3.12 CFFI; Hammerspoon is Lua in its own process. There is no in-process bridge. hs.ipc is a CLI that spawns a process per call — unusable at 100Hz; the surveyor listing "URL/IPC entry points" as a feature is accurate but those entry points are not a high-rate transport. Realistic designs: (a) hold a persistent hs.socket or hs.httpserver connection from Python; or (b) post cursor/click CGEvents straight from Python via pyobjc Quartz CGEventPost and use Hammerspoon only for what it is genuinely unmatched at — window management, app control, hotkeys, spaces, axuielement. Option (b) is likely the better split and keeps Hammerspoon off the per-frame hot path.

4. Permissions correction against the stated ground truth. "Accessibility is ALREADY granted to the terminal" does not carry over. Hammerspoon.app is a separately signed binary (Developer ID: Chris Jones, VQCYSNZB89) and needs its own Accessibility TCC grant before any eventtap posts or intercepts work. Expect a fresh prompt.

Risk to watch, not a blocker: #3831 reports multi-second to one-minute freezes on Tahoe/Sequoia. If it reproduces here it is disqualifying for a realtime input path, so exercise it on-machine before committing. Mitigation aligns with correction 3 — keeping Hammerspoon off the per-frame path also contains this risk.


## Lens: macos-action-injection

I did not just read docs — I compiled and ran three Swift probes (swiftc 6.3.3, target arm64-apple-macosx26.0) on the actual target machine (macOS 26.5.2, build 25F84) to measure this layer directly. Headline: CoreGraphics CGEventPost is fully alive and extremely fast — 10.4 µs per post, 93,930 posts/sec sustained, and a post→tap round trip of 0.43 ms median / 3.1 ms p95. Against the Leap's ~111 fps (9 ms/frame) budget, injection cost is effectively free, so the end-to-end latency of this project will be dominated by gesture recognition and smoothing, never by action injection. I disproved the most-cited 2026 claim in this space (Nick Liu's "macOS Tahoe silently drops synthesized hotkeys at the WindowServer level"): synthetic Cmd+Opt+; DID fire a Carbon RegisterEventHotKey handler on this machine, via both kCGHIDEventTap and kCGSessionEventTap — his failure was a missing NSApplication/Carbon event pump, not a Tahoe restriction. The real architecture is a two-tier one: CGEvent for continuous, low-level motion (cursor, scroll, drag, clicks) and the Accessibility API for semantic, discrete actions (press this button, set this text, invoke this menu item) — AX is more reliable because it needs no screen coordinates and no focus race. The genuine blockers are not event injection at all: they are Secure Event Input (any focused password field kills keyboard injection system-wide), and Screen Recording, which is NOT granted here and which Tahoe 26.1+ will not even display in the permissions UI for a non-bundled executable — that is the one thing that will actually bite an LLM computer-use loop.

| Candidate | Layer | Verdict | Last activity |
|---|---|---|---|
| [CoreGraphics CGEvent / CGEventPost](https://developer.apple.com/documentation/coregraphics/cgevent) | action-injection | **ADOPT** | Apple system framework, current on macOS 26.5.2 (build 25F84); CGPreflight/RequestPostEventAccess added 10.15 |
| [Secure Event Input (IsSecureEventInputEnabled)](https://developer.apple.com/documentation/carbon/1585158-issecureeventinputenabled) | action-injection | **—** | Apple system framework, current on macOS 26.5.2 |
| [Accessibility (AX) API — AXUIElement](https://developer.apple.com/documentation/applicationservices/axuielement_h) | action-injection | **ADOPT** | Apple system framework, current on macOS 26.5.2; still gaining uses in Tahoe (the new system-wide OTP autofill injects codes into browsers via AXUIElement) |
| [CGEventTap (CGEvent.tapCreate)](https://developer.apple.com/documentation/coregraphics/1454426-cgeventtapcreate) | action-injection | **ADOPT** | Apple system framework, current on macOS 26.5.2 |
| [Hammerspoon](https://github.com/Hammerspoon/hammerspoon) | orchestration | **ADOPT** | v1.1.1 released 2026-02-26; repo last pushed 2026-07-08; 15,919 stars |
| [Karabiner-Elements](https://github.com/pqrs-org/Karabiner-Elements) | action-injection | **—** | v16.1.0 released 2026-07-05; repo last pushed 2026-08-12 (very active); 22,633 stars; Unlicense (public domain) |
| [Karabiner-DriverKit-VirtualHIDDevice](https://github.com/pqrs-org/Karabiner-DriverKit-VirtualHIDDevice) | action-injection | **—** | v8.2.0 released 2026-07-20; repo last pushed 2026-08-09; 365 stars; Unlicense (public domain) |
| [kanata](https://github.com/jtroo/kanata) | action-injection | **—** | v1.12.0 released 2026-07-05; repo last pushed 2026-08-09; 7,748 stars; LGPL-3.0 |
| [BetterTouchTool](https://docs.folivora.ai/docs/scripting/url-scheme/) | orchestration | **—** | unknown — I did not establish a current version; it is closed source with no public repo, and it is not installed on this machine |
| [macOS Shortcuts CLI (/usr/bin/shortcuts)](https://support.apple.com/guide/shortcuts-mac/run-shortcuts-from-the-command-line-apd455c82f02/mac) | orchestration | **—** | ships with macOS 26.5.2 |
| [AppleScript / JXA (osascript, System Events)](https://developer.apple.com/library/archive/documentation/LanguagesUtilities/Conceptual/MacAutomationScriptingGuide/) | action-injection | **—** | ships with macOS 26.5.2 (both AppleScript and JXA) |
| [URL schemes via `open -g`](https://ss64.com/mac/open.html) | action-injection | **—** | ships with macOS 26.5.2 |
| [skhd](https://github.com/asmvik/skhd) | orchestration | **—** | repo last pushed 2025-12-09 — 8 months before today (2026-08-12); 8,068 stars; MIT |
| [yabai](https://github.com/asmvik/yabai) | orchestration | **—** | v7.1.25 released 2026-05-08; repo last pushed 2026-06-14; 29,451 stars; MIT |
| [AeroSpace](https://github.com/nikitabobko/AeroSpace) | orchestration | **—** | repo last pushed 2026-08-10 (2 days before today); 22,373 stars; MIT |
| [ScreenCaptureKit / Screen Recording permission](https://developer.apple.com/documentation/screencapturekit) | capture | **—** | Apple system framework, current on macOS 26.5.2; the APIs it replaces were deprecated in macOS 15.0 |

### CoreGraphics CGEvent / CGEventPost — ADOPT

```
There is no repository to fetch — this is an Apple system framework, so "last commit/release" is a category error. Currency was established from the on-machine SDK and live behavior instead.

HEADER EVIDENCE (macOS 26.5 SDK, /Library/Developer/CommandLineTools/SDKs/MacOSX.sdk, `xcrun --show-sdk-version` = 26.5, host macOS 26.5.2 build 25F84):
- CGEvent.h declares, with NO deprecation attribute: CGEventCreateMouseEvent (macos 10.4, L57), CGEventCreateKeyboardEvent (10.4, L79), CGEventCreateScrollWheelEvent (variadic, 10.5), CGEventCreateScrollWheelEvent2 (non-variadic, 10.13, L107), CGEventSetFlags (L182), CGEventKeyboardSetUnicodeString (L205), CGEventSetIntegerValueField (L226), CGEventPost (10.4, L353), CGEventPostToPid (10.11, L372).
- The ONLY deprecation in the whole header: L367 "DEPRECATED; use CGEventPostToPid instead" on CGEventPostToPSN. Nothing in the mouse/keyboard/scroll/post path is deprecated.
- CGPreflightPostEventAccess / CGRequestPostEventAccess / CGPreflightListenEventAccess / CGRequestListenEventAccess all present at L399-408, API_AVAILABLE(macos(10.15)) — surveyor's 10.15 claim confirmed verbatim.
- CGEventTypes.h confirms kCGMouseEventClickState=1 (L148), kCGScrollEventUnitPixel=0 / kCGScrollEventUnitLine=1 (L47-48), kCGHIDEventTap=0 / kCGSessionEventTap=1 / kCGAnnotatedSessionEventTap=2 (L403-405), kCGEventSourceStateHIDSystemState=1 (L483).

ARM64: `uname -m` = arm64; framework lives in dyld_shared_cache_arm64e (/System/Volumes/Preboot/Cryptexes/OS/System/Library/dyld/); loaded and called successfully from arm64-native /opt/homebrew/bin/python3 via ctypes. Not Leap-specific, so libLeapC.6 compatibility is a non-question — it is a pure output-side API.

MY OWN MEASUREMENTS (independent re-derivation, macOS 26.5.2, today; scripts at /private/tmp/claude-501/-Users-joerup-era-era-memory-evals/1f99f28d-32a3-423c-93b9-1778e24655e6/scratchpad/{cgverify,movetest,movetest2,taptest,taptest2,ratetest,perf}.py):
- CGPreflightPostEventAccess() = True, CGP
```

**Corrections:** Six corrections/additions. None of them change the verdict, but three are load-bearing for the build.

1. Not a repo. "Fetch the actual repository / last-commit date" does not apply — it ships in the dyld shared cache with the OS. The right currency proof is the SDK header + live behavior, which I used. The surveyor's "current on macOS 26.5.2" claim is correct as stated.

2. API spellings are Swift-only. The surveyor quoted `CGEvent(mouseEventSource:...)`, `CGEvent(keyboardEventSource:...)`, `CGEvent(scrollWheelEvent2Source:...)`. Those are the Swift-imported initializers. If you drive this from Python/ctypes (which you must, since the working Leap binding is a CPython 3.12 venv), the symbols are CGEventCreateMouseEvent / CGEventCreateKeyboardEvent / CGEventCreateScrollWheelEvent2 / CGEventPost. Also: ...ScrollWheelEvent2 is the non-variadic variant added in 10.13; the 10.5 variadic CGEventCreateScrollWheelEvent is unusable from ctypes and should be avoided.

3. MATERIAL — tap location is not free choice. The surveyor says ".post(tap:)" as if any tap works. kCGAnnotatedSessionEventTap (2) does NOT move the pointer: my measured errors were 700 / 380 / 850 px vs 0.0 px at kCGHIDEventTap and kCGSessionEventTap. Use tap 0 (or 1); never 2 for cursor control.

4. MATERIAL — my first two measurement passes appeared to show 40-70 px positioning error, and that was a measurement artifact worth recording so nobody re-derives a false bug: (a) CGEventCreate(NULL)+CGEventGetLocation lags the post — it converges to the exact target within ~5 ms, but reading at 0 ms returns the previous position; (b) the physical pointer was being driven concurrently (passive sampling with zero events posted showed the cursor drifting on its own, and Ultraleap Control Panel was at ~42% CPU), which overrides posted absolute positions. Synthetic and physical input contend on the same cursor — a Leap loop posting at 111 Hz will fight the trackpad, and there is no "grab" primitive. CGWarpMouseCursorPosition is the exact alternative (3/3 at 0.0 px) but emits no mouse-moved event, so apps tracking hover will not see it; the warp-then-post-move hybrid also measured 4/4 at 0.0 px if you need both.

5. MATERIAL — "app menu shortcuts" is narrower than claimed. The measured Cmd+A/Cmd+C in TextEdit are Cocoa menu key equivalents, dispatched inside the target app, and they do work. Carbon RegisterEventHotKey global hotkeys registered by third-party apps are separately gated by WindowServer's CGXSenderCanSynthesizeEvents for unsigned/ad-hoc-signed senders and may silently not fire — so "drive any app by its global hotkey" is not a safe assumption. Prefer menu-item invocation via the Accessibility API, or an app's URL scheme, for cross-app control.

6. Missing caveats the surveyor did not mention: (a) Secure Input — any password field, or Terminal's "Secure Keyboard Entry", blackholes synthetic keystrokes with no error; check for kCGSSessionSecureInputPID before blaming your code (it is clear right now). (b) Packaging — the granted Accessibility/PostEvent right belongs to the responsible host app (your terminal). A standalone daemon or LaunchAgent needs its own grant, and bare Unix executables could not be registered at all on macOS 26.0-26.2 (fixed in 26.3; you are on 26.5.2). Ship the gesture daemon inside a signed .app bundle, and gate startup on CGPreflightPostEventAccess() with CGRequestPostEventAccess() as the prompt path rather than assuming the right.


### Secure Event Input (EnableSecureEventInput / IsSecureEventInputEnabled, Carbon HIToolbox) — ADOPT

```
Not a repo — an Apple system API. No commits/releases to date; currency established by SDK and runtime probing on the target machine (macOS 26.5.2 / 25F84, arm64) on 2026-08-12. All results below are measured, not read.

EXISTENCE / ARCH / CURRENCY
- Carbon.framework and its HIToolbox subframework are present and current: /System/Library/Frameworks/Carbon.framework/Versions/A/Frameworks/HIToolbox.framework (dated 2026-06-24, i.e. shipped with 26.5.2).
- Symbols exported in the 26.5 SDK stub /Library/Developer/CommandLineTools/SDKs/MacOSX.sdk/.../HIToolbox.framework/HIToolbox.tbd: `_EnableSecureEventInput`, `_DisableSecureEventInput`, `_IsSecureEventInputEnabled`. tbd targets: `[ x86_64-macos, arm64e-macos ]`, current-version 1250.1. Also re-exported from Carbon.tbd.
- CoreGraphics.tbd additionally exports the private `_CGSIsSecureEventInputSet` / `_CGSSetSecureEventInput`. Do not use those; the Carbon pair is the public path.
- Built and ran natively: `clang -arch arm64 -framework Carbon` → `Mach-O 64-bit executable arm64`, `IsSecureEventInputEnabled = 0`. Confirms the surveyor's baseline reading.

GOTCHA THE SURVEYOR MISSED: NO PUBLIC HEADER
- `grep -rl "SecureEventInput"` across the entire 26.5 SDK Frameworks tree hits ONLY three .tbd stub files. There is no declaration in any Carbon/HIToolbox header any more. You must write your own `extern Boolean IsSecureEventInputEnabled(void);` (worked; that is how every probe here compiled). Linkable, not header-declared.
- The cited doc URL https://developer.apple.com/documentation/carbon/1585158-issecureeventinputenabled returns HTTP 404. The surviving authoritative reference is TN2150 "Using Secure Event Input Fairly" (developer.apple.com/library/archive/technotes/tn2150/), dated 2007-06-08 and banner-marked "This document is no longer being updated."

MEASURED BEHAVIOUR — assertion
- A plain unbundled, non-GUI, non-frontmost CLI binary called `EnableSecureEventInput()` → OSStatus 0, and the flag went system-wide: an unre
```

**Corrections:** Three corrections, one of them material.

1. WRONG — "synthetic key events are dropped." They are not. Measured 3/3 CGEventPost keydowns delivered to a frontmost AppKit app in all three configurations, including when that app asserted secure input on itself. TN2150 backs this: the mechanism is defined against *interception* (seize / event tap / GetKeys), never against posting. This is the load-bearing error — the surveyor framed this as a hazard that breaks action-injection, and it does not break action-injection at all.

2. MISLEADING — "routes keyboard input directly to the focused process, bypassing the CGEvent pipeline entirely." The CGEvent pipeline is not bypassed. The tap stays created, stays enabled, gets no disable notification, and keeps delivering mouse events at full rate; only keyDown/keyUp/flagsChanged are filtered out of tap delivery. It is a per-event-type visibility filter on interception, not a pipeline bypass.

3. INCOMPLETE — "Apple system framework, current on macOS 26.5.2." True at the link layer, but the function is no longer declared in any public header in the 26.5 SDK (only in the .tbd stubs), so callers must supply their own `extern` declaration. And the cited documentation URL is a 404; the only surviving Apple reference is TN2150, archived and frozen at 2007-06-08.

CORRECT AS CLAIMED: `IsSecureEventInputEnabled()` reads false on this machine right now (independently reproduced); any app can assert it (verified stronger than claimed — an unentitled, unbundled, non-frontmost CLI flipped it system-wide); event taps do go blind to keystrokes while engaged.

SCOPE FOR THIS PROJECT: the hazard is real but far narrower than presented. It costs nothing for cursor control, clicks, scroll, keyboard shortcut injection, app control, or driving an LLM computer-use loop — all of those are posting, and posting works under SEI. It costs exactly one thing: any design that *reads* the keyboard via a CGEventTap (e.g. a chord scheme where a held modifier arms a gesture, or a keyboard-activity idle detector) goes silently blind whenever a password field, lock screen, or Terminal secure-keyboard-entry has focus — no error, no tap-disabled callback, just zero events. Design rule: never make gesture arming depend on tap-observed key state; if you must, call IsSecureEventInputEnabled() as a preflight and degrade to a gesture-only or mouse-only arming path. Adopted as a two-line preflight probe plus that one architectural constraint, not as a threat to the injection layer.


### Accessibility (AX) API — AXUIElement — ADOPT

```
NOT A REPOSITORY — Apple system framework, so "last commit / last release" and libLeapC.6 compatibility are N/A. Verified against the on-machine SDK header and live processes, not the web.

SDK PRESENCE (authoritative, on-machine)
/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk/System/Library/Frameworks/ApplicationServices.framework/Versions/A/Frameworks/HIServices.framework/Headers/AXUIElement.h — 669 lines, SDK 26.5. Exports AXUIElementCreateApplication, CreateSystemWide, CopyAttributeValue(s), CopyMultipleAttributeValues, CopyAttributeNames, IsAttributeSettable, SetAttributeValue, CopyActionNames, PerformAction, CopyElementAtPosition, CopyParameterizedAttributeValue, GetPid, SetMessagingTimeout, plus AXObserverCreate / AXObserverCreateWithInfoCallback / AXObserverAddNotification. Exactly THREE symbols in the whole header carry CF_DEPRECATED_MAC: AXAPIEnabled (10.9), AXMakeProcessTrusted (10.9), AXUIElementPostKeyboardEvent (10.9). Everything the candidate claims is non-deprecated. AXIsProcessTrustedWithOptions is CF_AVAILABLE_MAC(10_9) and current.

LIVE READS — macOS 26.5.2 (25F84), arm64, AXIsProcessTrusted()==true, no prompt (inherits the terminal's existing grant; freshly-compiled ad-hoc binaries were trusted with no re-prompt across four rebuilds)
Per-app AXUIElementCreateApplication + kAXWindows / kAXMenuBar / kAXFocusedUIElement all err=0 on Safari(2 win, 9 menus), Slack(1,9), VS Code(3,11), Notion(1,8), Notes(1,8), Warp(1,11), System Settings(1,6), Finder. win0 kAXTitle read live e.g. Slack "* canessa (Channel) - Era Laboratories - Slack". kAXPosition settable==true on every AXWindow tested.

LIVE WRITES / ACTIONS (all reverted)
- kAXValue write, zero event synthesis: TextEdit AXTextArea, IsAttributeSettable=true, SetAttributeValue err=0, read-back "REPLACED-BY-AX". kAXSelectedTextRange set err=0 → kAXSelectedText returned "REPLACED".
- AXPress on a real menu item: TextEdit Format > "Make Rich Text" err=0, menu item title changed afterward (verified b
```

**Corrections:** Four corrections; none change the ADOPT, but two change how it must be used.

1. "Claimed layer: action-injection" is MISLEADING — AX cannot inject input at all. There is no pointer API in the framework (grepped: zero Move/Mouse/Click symbols), and the only key-posting function, AXUIElementPostKeyboardEvent, is CF_DEPRECATED_MAC(10_0, 10_9) and is a HARD COMPILE ERROR in Swift: "'AXUIElementPostKeyboardEvent' is unavailable in macOS: APIs deprecated as of macOS 10.9 and earlier are unavailable in Swift". AX injects *semantic actions* (AXPress/AXPick/AXRaise) and *state writes* (kAXValue, kAXPosition, scrollbar value). Cursor motion, coordinate clicks, wheel scroll and raw shortcuts still require CGEventPost. AX is the complement to CGEvent, not a replacement — architect the gesture system with both.

2. "Semantic, coordinate-free app control" is NOT free on Electron. VS Code exposed only 12–13 nodes / depth 6 / 3 pressable — an opaque shell. Fix: AXUIElementSetAttributeValue(app, "AXManualAccessibility", kCFBooleanTrue) → err=0, tree grew to 563→595 nodes. Critically it is ASYNCHRONOUS: still 13 nodes at t+2s, populated by t+6s, so a naive probe reports failure. (I initially measured this as a hard failure and had to re-test.) AXEnhancedUserInterface returned -25208 (attributeUnsupported) on VS Code — don't use it. Slack (542 nodes) and Notion (1101) needed no opt-in. Budget for a per-app enablement + settle step, and note it imposes an ongoing accessibility-tree cost inside the target app.

3. The OTP-autofill supporting claim is UNSUBSTANTIATED — drop it. macOS Tahoe 26 one-time-code autofill for third-party browsers is real, but no source ties its implementation to AXUIElement, and Apple actually RESTRICTED it for non-Safari browsers in 26.1 (Opera forum thread, MacRumors 2025-06-12). It is weak evidence pointing the wrong direction; the header and the live measurements are the evidence that matters.

4. The cited URL resolves (title "AXUIElement.h | Apple Developer Documentation") but Apple's docs are a JS SPA — WebFetch returns only the title, no body, so it cannot corroborate anything. Cite the on-machine header instead.

Minor: AXUIElementCreateSystemWide's kAXFocusedUIElement returned cannotComplete while a system auth panel (universalAccessAuthWarn) was frontmost, so the system-wide focus path needs a per-app kAXFocusedUIElement fallback. Also note the TCC grant follows the responsible binary — it is currently inherited from the terminal; a shipped .app bundle will need its own Accessibility grant.


### CGEventTap (CGEvent.tapCreate) — ADOPT

```
NOT A REPO — Apple system framework, so "last commit/release" and "libLeapC.6 compatibility" are N/A. Verified against the live macOS 26.5.2 SDK and by six compiled Swift probes run on the target machine (source in /private/tmp/claude-501/-Users-joerup-era-era-memory-evals/1f99f28d-32a3-423c-93b9-1778e24655e6/scratchpad/tapverify/).

CURRENCY / DEPRECATION (header is stronger evidence than the doc page, which is a JS SPA that WebFetch could not read):
/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk/.../CoreGraphics.framework/Headers/CGEvent.h:296 declares CGEventTapCreate with `API_AVAILABLE(macos(10.4))` and NO deprecation attribute. The only "DEPRECATED" string in CGEvent.h is at line 367 and refers to CGEventPostToPSN, not taps. Live in the macOS 26 SDK.

ARM64: swiftc 6.3.3, target arm64-apple-macosx26.0, native. All probes compiled and ran.

CREATION — 12/12 combos, as an unprivileged CLI binary (uid=euid=501, AXIsProcessTrusted()=true):
{cghidEventTap, cgSessionEventTap, cgAnnotatedSessionEventTap} x {listenOnly, defaultTap} x {mouse mask, keyboard mask} → all created=YES enabled=YES. Notably cghidEventTap works WITHOUT root, contradicting common lore.

DELIVERY — 100%, ambient baseline clean:
3s with zero injection → 0 events (no ambient noise). 25 tagged mouseMoved injected → 25 observed, 1:1. Separately 120/120 delivered in the latency probe.

SUPPRESSION IS REAL (the claim's most important untested half):
Upstream defaultTap at cghidEventTap returning nil, downstream listenOnly observer at cgAnnotatedSessionEventTap. Pass-through phase: upstream 58 / downstream 58. Suppression phase: upstream 118 / downstream 0. Events are genuinely killed before reaching downstream consumers.

OPTION SEMANTICS CONFIRMED: a .listenOnly tap returning nil is ignored — injected=40, upstream(listenOnly, returned nil)=40, downstream=40. listenOnly cannot suppress; only .defaultTap can.

LATENCY (post → tap callback, own clock, tagged events, n=120/120): min 0.179 ms, median
```

**Corrections:** 1. LAYER IS MISLABELED — the significant correction. "Claimed layer: action-injection" is wrong. CGEventTap is an INTERCEPTION layer: it observes, mutates, or drops events it is handed. It cannot originate an event. Injection is CGEventPost/CGEventPostToPid (a separate API, already in your ground truth). For the Leap system these are two distinct components: CGEventPost drives the cursor/clicks; CGEventTap is only needed if you want to intercept or suppress REAL input (e.g. swallow the physical trackpad while a hand is tracked, or bind a gesture to swallow a key). Do not treat this candidate as the injection mechanism — it is not, and confusing them will misshape the architecture.

2. UNDER-TESTED, not wrong. The surveyor tested only .listenOnly at 2 of 3 locations. Their "40/40 and 5/5" numbers reproduce fine, but .listenOnly is the option that cannot do anything to the event stream, so it is the half that carries no risk. I extended to all 3 locations x both options x mouse and keyboard masks (12/12) and confirmed .defaultTap suppression genuinely works. The claim is accurate as far as it goes; it just did not test the part that matters.

3. MISSING: the watchdog. Nothing in the claim mentions kCGEventTapDisabledByTimeout. Measured: 4s of blocking in the callback silently disables the tap and drops all subsequent events. A tap MUST subscribe to the tapDisabledByTimeout/tapDisabledByUserInput event types and call tapEnable(true) on receipt, plus run a periodic tapIsEnabled health check. This is the single most likely way a working prototype dies in the field.

4. MISSING: "created and enabled" is not "healthy". tapCreate returning non-nil and tapIsEnabled returning true at install time both hold in the known-broken re-signing case. Health must be checked continuously at runtime, not at creation.

5. MISSING: permission nuance. It works here only because Accessibility is already granted (your ground truth) and Accessibility supersedes Input Monitoring. A shipped/signed/re-signed bundle is a different TCC identity than the terminal and will need its own grant — the current success does not transfer to a packaged app.

6. MEASUREMENT CONTAMINATION WARNING for whoever re-runs this: concurrent sibling agent sessions were live on this machine during probe 2 (`cua-driver call move_cursor` and `gesture_flag_probe.py --microgestures`, PIDs 47533/49850), injecting their own cursor moves. That inflated raw counts above injected counts and warped the cursor to x=0 mid-test. It is NOT a CGEventTap defect. Any future event measurement on this box must tag its own events via eventSourceUserData and filter, as probes 3/5/6 do — untagged counting here produces wrong numbers.

7. Minor: the cited URL is the legacy Objective-C page (CGEventTapCreate); the Swift entry point is CGEvent.tapCreate(tap:place:options:eventsOfInterest:callback:userInfo:). Also note a tap requires a running CFRunLoop with the mach port source attached — a tap created without one is inert and looks identical to a permissions failure.


### Hammerspoon — ADOPT

```
REPO STATE (GitHub API, 2026-08-12): Hammerspoon/hammerspoon, MIT, 15,919 stars, archived=false, disabled=false, default branch master, lang Objective-C. Last push 2026-07-08T21:13:24Z (commit "hs.urlevent: match event names case-insensitively" by outside contributor TowyTowy). Latest release v1.1.1 published 2026-02-26T10:52:34Z. Surveyor's three headline numbers (v1.1.1 / 2026-02-26, pushed 2026-07-08, 15,919 stars) are all EXACT.

RELEASE LINE: 1.1.1 (2026-02-26), 1.1.0 (2025-12-24), 1.0.0 (2024-08-06), 0.9.100 (2023-03-14). Both 1.1.0 and 1.1.1 postdate the macOS 26/Tahoe release, so the current build is Tahoe-era, not pre-Tahoe.

ARM64 + macOS VIABILITY (verified by downloading and inspecting the actual 1.1.1 asset): `lipo -archs` → "x86_64 arm64" — genuine universal binary, native Apple Silicon. Info.plist LSMinimumSystemVersion = 13.0, confirming the min-macOS-13 claim. Homebrew cask resolves to 1.1.1 with an arm64_tahoe JSON API package, Required: macOS >= 13.

ON-MACHINE GATEKEEPER CHECK (strongest single piece of evidence, run here on macOS 26.5.2): `codesign -dv` → Authority "Developer ID Application: Chris Jones (VQCYSNZB89)", secure timestamp Feb 26 2026, chained to Apple Root CA. `spctl -a -vvv -t install` → "accepted / source=Notarized Developer ID". The signed, notarized 1.1.1 build is accepted by Gatekeeper on this exact machine.

API SURFACE — 20/20 CLAIMED CALLS VERIFIED present in the shipped bundle's own docs.json (140 modules), not from docs or memory: hs.eventtap.event.newMouseEvent/newKeyEvent/newScrollEvent (all Constructor), hs.eventtap.keyStroke/keyStrokes (Function), hs.eventtap.new/start, hs.mouse.absolutePosition/getRelativePosition/trackingSpeed, hs.spaces.moveWindowToSpace/activeSpaceOnScreen, hs.ipc.cliInstall, hs.hotkey.bind, hs.window.focusedWindow, hs.application.launchOrFocus. Signature `hs.mouse.trackingSpeed([speed],[trackpad])` confirms the Mar-2025 "fixes mouse tracking speed actually being changed; adds trackpad tracking spe
```

**Corrections:** 1. "Actively maintained" is the one materially overstated claim. Commits per year by committer date: 518 (2023) → 60 (2024) → 24 (2025) → 3 (2026 YTD, and it is August). Only 8 PRs merged and 11 issues closed in the last 12 months, against 681 open issues and 21 open PRs whose oldest dates to April 2021. It is a single-maintainer (cmsj) project in batched, low-throughput maintenance mode — merges land in occasional bursts (2025-11-18, 2025-12-24). Correct framing: mature and feature-complete, still shipping signed/notarized releases, but do NOT expect an upstream fix if you hit a bug. Budget for patching it yourself or working around it. This does not sink the verdict, because the API needed here is stable and long-settled, not under development.

2. Accessibility permission does NOT carry over. Ground truth says the terminal already has Accessibility so CGEventPost lands — true, but macOS TCC grants are per-binary. Hammerspoon.app is a separate app and will require its own Accessibility grant (and its own Input Monitoring grant for eventtap listeners) before any synthesized event or keyboard tap works. This is a first-run setup step the survey did not flag.

3. Architectural correction on where to use it. Routing the cursor hot path through Hammerspoon is the wrong shape for this system: the Leap bindings run in a Python 3.12 venv at ~111 fps, so sending every frame across an IPC hop into Lua adds latency and a failure mode for no benefit — Python can call CGEventPost directly via pyobjc/Quartz, and the terminal already holds the Accessibility grant. Hammerspoon earns its place for what Python does badly: window/app/Spaces management (hs.window, hs.application, hs.spaces), global hotkeys, chooser UI, and app-scoped modal state. Recommended split is Python owns pointer motion/clicks/scroll, Hammerspoon owns discrete window-and-app orchestration, bridged over hs.httpserver or hs.socket. Also avoid hs.window.filter specifically — it is the subsystem implicated in the Tahoe freeze reports.

4. Minor: hs.ipc.cliInstall() defaults to /usr/local/bin, which is not a default-writable or default-PATH location on Apple Silicon; installing the `hs` CLI will need an explicit path argument or sudo.

5. Not a correction but worth stating: "NOT currently installed" is confirmed — `which hs` → not found, no Hammerspoon.app in /Applications, not in the brew cask list. Everything above was verified against the freshly downloaded 1.1.1 release artifact, not an installed copy, so runtime behavior of eventtap under sustained high-rate posting remains the one thing unproven on this machine.


## Lens: gesture-recognition-layer

The decisive finding is that you do not need to invent a gesture layer — Ultraleap already wrote and production-tuned one, and its source is Apache-2.0 and readable. `ultraleap/TouchFree` (archived 2023-04-21) contains `TF_Service_dotNet/TouchFree/Interactions/` with AirPush, AirClick, HoverAndHold, TouchPlanePush, VelocitySwipe, a GeneralisedGrabDetector, a PositionStabiliser (deadzone), and 1€-filter/extrapolation position modifiers. The shipped TouchFree *binary* being Windows-only is irrelevant: the algorithms are ~200-line pure-math C# classes operating on exactly the fields LeapC gives you, and I extracted their real default constants (listed per-candidate below). Porting these to Python is a days-not-weeks job and should be the backbone of the system. Second: I found gesture detection is now partly in the SDK itself — `LeapC.h` on this machine defines `eLeapHandFlag_GestureDetectionAvailable / GesturePinch / GestureMovingPinchOpening / GestureMovingPinchClosing` (all `@since 6.2.0`) on `LEAP_HAND.flags`, and the vendored Python binding at `/Users/joerup/era/leap-input/vendor/.../datatypes.py:174` already exposes `hand.flags`. If those bits fire on the v1, server-side pinch detection is free and you skip the hardest hysteresis tuning entirely — but I could not confirm they fire, because no hand was over the device during my probe (`hand_frames=0`). That is the single highest-value five-minute experiment remaining. Third, I am opinionated against learned classifiers for the core interactions: `pinch_strength`/`grab_strength` are *already* Hyperion ML outputs, so a trained model on top is a second classifier stacked on a first, adding latency and non-determinism to solve a problem a Schmitt trigger solves. Reserve learning for user-enrolled dynamic path gestures, and there use DTW (ISUE/Jackknife, 1-2 samples/class, no training infra) before reaching for DeepGRU. Finally, Ultraleap microgestures (thumb-sliding-on-index tap/swipe/scrub) are the one design reference I would explicitly *not* chase on this hardware — they require millimetre thumb-index resolution that a 2013 640x240 IR sensor does not have, and the enabling `LEAP_HINT_MICROGESTURES` hint additionally requires a multi-device-aware connection plus a Hyperion license.

| Candidate | Layer | Verdict | Last activity |
|---|---|---|---|
| [ultraleap/TouchFree — service interaction modules (THE reference implementation)](https://github.com/ultraleap/TouchFree/tree/develop/TF_Service_dotNet/TouchFree/Interactions) | gesture-recognition | **—** | code last pushed 2023-04-21; repo archived (read-only). Apache-2.0, 28 stars. |
| [LeapC 6.2 built-in gesture flags (already on this machine)](https://docs.ultraleap.com/api-reference/tracking-api/leapc-guide.html) | gesture-recognition | **—** | SDK build in use is v6.2.0-c98d293a, installed and running now |
| [ISUE/Jackknife — DTW few-shot gesture recognizer](https://github.com/ISUE/Jackknife) | gesture-recognition | **TRIAL** | last pushed 2024-01-25; not archived; 21 stars; license NOASSERTION (check before shipping) |
| [casiez/OneEuroFilter — 1€ adaptive smoothing filter](https://github.com/casiez/OneEuroFilter) | gesture-recognition | **ADOPT** | pushed 2026-08-05 (actively maintained); 244 stars |
| [ultraleap/UnityPlugin — HandPoseDetector (static pose matching)](https://github.com/ultraleap/UnityPlugin/blob/main/Packages/Tracking/Core/Runtime/Scripts/HandPoses/HandPoseDetector.cs) | gesture-recognition | **ADOPT (as algorithm source / design reference — not as an installable dependency)** | pushed 2026-07-07 — the most actively maintained Ultraleap OSS repo; Apache-2.0, 589 stars |
| [Maghoumi/DeepGRU — deep gesture recognition utility](https://github.com/Maghoumi/DeepGRU) | gesture-recognition | **—** | last pushed 2024-07-25; MIT licence; 24 stars |
| [DDlabAU/LeapMotion-Python-Hyperion — the binding already vendored and working](https://github.com/DDlabAU/LeapMotion-Python-Hyperion) | capture | **—** | pushed 2025-10-22 (upstream ultraleap/leapc-python-bindings has been static since 2024-06-24) |
| [studiome/LeapSwift — native macOS Swift framework](https://github.com/studiome/LeapSwift) | capture | **—** | pushed 2026-08-03 — nine days ago, the most recently active LeapC project found |
| [Ultraleap Microgestures (Hyperion v6) — the design reference to NOT chase on this hardware](https://docs.ultraleap.com/xr-guidelines/Interactions/microgestures.html) | gesture-recognition | **—** | docs current for Hyperion 6.x; reference repo pushed 2025-02-14 (1 commit) |
| [ultraleap/TouchFreeWebTooling + TouchFree-Tooling-Examples](https://github.com/ultraleap/TouchFreeWebTooling) | orchestration | **—** | pushed 2024-05-20; Apache-2.0; 16 stars |
| [DTW toolkits — tslearn and dtaidistance](https://github.com/tslearn-team/tslearn) | gesture-recognition | **—** | both pushed within the last five weeks; tslearn updated today |

### ultraleap/TouchFree — TF_Service_dotNet interaction modules — TRIAL

```
REPO STATE (gh api repos/ultraleap/TouchFree): archived=true, pushed_at=2023-04-21T14:52:59Z, created 2020-10-12, default_branch=develop, stars=28, forks=12, license=Apache-2.0 (LICENSE in tree is the real Apache 2.0 text), open_issues=0. Last commit on develop: 7452704d 2023-04-21T14:35:58Z "Merge pull request #494 from ultraleap/feat/TF-1247_archive-github-repo" — the final commit is literally the archive commit. GitHub Releases list is EMPTY; versioning was via tags, newest product tag release/App_And_Service/2.6.0. All 12 forks sit at the same archive SHA or older (newest three: ICpachong, DS-T, mattgrayy all pushed=2023-04-21T14:52:59Z) — zero community continuation. README "Notice: Content for this repository has moved" points to the closed-source TouchFree installer plus TouchFreeWebTooling (unarchived, pushed 2024-05-20) and TouchFreeUnityTooling (pushed 2023-05-02) — both are CLIENT tooling and contain none of this interaction math. This archived repo is the only public source of the engine.

CODE EXISTS AND CONSTANTS ARE EXACT. Read TF_Service_dotNet/TouchFree/Configuration/InteractionConfigInternal.cs directly. Every claimed value is verbatim correct: AirPush SpeedMin=150f/SpeedMax=500f, DistAtSpeedMinMm=42f, DistAtSpeedMaxMm=8f, HorizontalDecayDistMm=50f, ThetaOne=65f, ThetaTwo=135f, UnclickThreshold=0.97f, ForceDecayTime=0.1f, DistPastTouchPlaneMm=20f, DragStartDistanceThresholdMm=30f, DeadzoneMaxSizeIncreaseMm=20f, DeadzoneShrinkRate=0.8f; VelocitySwipe MinScrollVelocity_mmps=625f, MaxReleaseVelocity_mmps=200f, MaxLateralVelocity_mmps=300f, MaxOpposingVelocity_mmps=65f, MinSwipeLength=10f, MaxSwipeWidth=10f, SwipeWidthScaling=0.2f, ScrollDelayMs=450; HoverAndHold HoverStartTimeS=0.5f/HoverCompleteTimeS=0.6f; global DeadzoneRadiusMm=3f, InteractionMaxDistanceMm=250.0f. AirClickInteraction.cs:25-26 `_maxAngleChange = 30` / `_minAngleChangePerSecond = 180`. GeneralisedGrabDetector.cs:7-8 GrabThreshold=0.8f / UngrabThreshold=0.7f. HoverAndHoldInteraction.c
```

**Corrections:** Constants are 100% accurate. Eleven corrections, mostly scope and file-path errors, none fatal:

1. WRONG PATHS. The modules are NOT flat in Interactions/. They live in Interactions/InteractionModules/ (AirClick, AirPush, Grab, HoverAndHold, TouchPlanePush, VelocitySwipe, plus IInteraction/InteractionModule/InputActionResult) and Interactions/GrabDetector/GeneralisedGrabDetector.cs.

2. SIX INTERACTION MODULES, NOT FIVE. The surveyor omitted GrabInteraction.cs. ServiceTypes.cs:44 `enum InteractionType { GRAB, HOVER, PUSH, TOUCHPLANE, VELOCITYSWIPE, AIRCLICK }` and ServiceCollectionExtensions.cs:72-77 registers all six as IInteraction singletons. Grab is a first-class selectable mode, not just a helper for the detector.

3. "DEPENDENCY-FREE PURE-MATH CLASSES" IS OVERSTATED. InteractionModule.cs:34-41 — the base constructor requires IHandManager, IVirtualScreen, IConfigManager, IClientConnectionManager, IPositioningModule, IPositionStabiliser. AirPushInteraction.cs:182 calls `VirtualScreen.PixelsToMillimeters(dPerpPx)`. The Interactions folder alone does not yield a screen-space cursor: you also need VirtualScreen.cs + PhysicalConfigInternal.cs (screen size mm/px, LeapPositionRelativeToScreenBottomMm default (0,-120,-250), ScreenRotationD) + Utilities.cs. The conclusion survives (all of it is platform-free math), but real port scope is ~2,400 LOC, not "the Interactions folder".

4. PositionFilter IS NOT A CANONICAL 1€ FILTER. It is a simplified variant with a HARDCODED 60 Hz sample rate: `CalculateAlpha(cutOff) => 1f / (1f + (60f / (2f*PI*cutOff)))`, with _beta=0.1f, _dcutoff=_mincutoff=0.5f. It never uses per-sample dt. This machine streams ~111 fps (ground truth), so a literal port is mis-tuned by ~1.85x — the port MUST substitute a real dt-driven 1€ filter, not transliterate this one.

5. THREE OF THE ADVERTISED FEATURES ARE OFF BY DEFAULT. InteractionTuning.cs is a record of four bools all defaulting to `default` (=false): EnableInteractionConfidence, EnableAirClickWithAirPush, EnableOneEuroFilter, EnableExtrapolation. So PositionFilter.cs `_enabled` is false and ExtrapolationPositionModifier is inactive in shipped defaults. Do not assume the smoothing/extrapolation path was production-hardened — it was experimental tuning.

6. THE `confidence` PATH IS INERT ON HYPERION. AirPushInteraction.cs:185 multiplies force change by `confidence`, but LeapC.h documents LEAP_HAND.confidence as "Not currently used (always 1.0)". Porting the confidence multiply is dead weight.

7. "arm64-macOS capable" — NOT AS SHIPPED. RuntimeIdentifiers are win-x64;linux-arm64;linux-x64. The only ARM64 target is BrightSign Linux (`<Platforms>AnyCPU;ARM64</Platforms>` gated on `$(BRIGHTSIGN)=='true'`), not macOS. Plus a Microsoft.Win32.Registry dependency in the same project. The surveyor's macOS "yes" is only defensible as "port the math to Python", which is what they recommend — but nobody should try to `dotnet build` this on this Mac.

8. LEAPC VINTAGE NOT MENTIONED. Bundled natives are LeapC v5 (libLeapC.so.5). Never exercised against libLeapC.6 / Hyperion 6.2. Confined to the wrapper layer we replace with leapc-python-bindings, so it is a caveat rather than a blocker.

9. NO RELEASES OBJECT. Surveyor said nothing false here, but for the record GitHub Releases is empty; the version history is in `release/*` tags only.

10. MISSING CONSTANTS worth capturing for the port: TouchPlaneActivationDistanceMm=50f with TouchPlaneTrackedPosition=NEAREST; AirPush UnclickThresholdDrag=0.97f, DragDeadzoneShrinkRate=0.9f, DragDeadzoneShrinkDistanceThresholdMm=10f, DecayForceOnClick=true, UseTouchPlaneForce=true; VelocitySwipe UpwardsMinVelocityDecrease=50f, DownwardsMinVelocityIncrease=50f, AllowBidirectionalScroll=false, AllowHorizontalScroll=true, AllowVerticalScroll=true; HoverAndHold _hoverDeadzoneEnlargementDistance=5f, _timerDeadzoneEnlargementDistance=5f, _deadzoneShrinkSpeed=0.3f; AirClick _dragStartDistanceThresholdMm=30f; global InteractionMinDistanceMm=0f, InteractionZoneEnabled=false, UseScrollingOrDragging=true, UseSwipeInteraction=false, default InteractionType=PUSH.

11. UNDERSOLD: the repo ships a real test suite (TouchFreeTests/) including PositioningModuleTests, PositionStabiliserTests, VirtualScreenTests, InteractionManagerTests and per-tracker tests (IndexTip/IndexStable/Nearest/Wrist). Those are portable oracles for validating a Python reimplementation — the single strongest argument for TRIAL over REJECT, and the surveyor did not mention them.

VERDICT REASONING: not ADOPT — the repo is archived read-only, dead since 2023-04-21, has no macOS build target, no releases, no fork continuation, and zero chance of upstream fixes; nothing here is "directly usable" on this machine. Not REJECT — unlike the shipped Windows-only TouchFree app (correctly listed as a dead end in ground truth), this source tree is Apache-2.0, algorithmically real, verified constant-for-constant, free of any OS API, reads only LEAP_HAND fields that Hyperion 6.2 still exposes, and comes with a portable test suite. TRIAL: adopt it as a specification to reimplement in Python against the working 3.12 venv bindings, starting with AirPush + PositionStabiliser + VirtualScreen; replace PositionFilter with a proper dt-driven 1€; drop the confidence multiply and the Registry-backed config loader.


### LeapC 6.2 built-in gesture flags (eLeapHandFlag) — Hyperion 6.2 SDK, local — REJECT

```
NOT A REPOSITORY — this is a vendor SDK surface, so verification was on-machine + vendor docs rather than commit history. Build in use: Hyperion 6.2.0.0, libtrack_server + libLeapC.6.dylib both Mach-O arm64 (native, no Rosetta), binaries dated 2025-09-19, server reports v6.2.0-c98d293a.

HEADER CLAIM — CONFIRMED VERBATIM. /Applications/Ultraleap Hand Tracking.app/Contents/LeapSDK/include/LeapC.h:1675-1687 defines eLeapHandFlag with GestureDetectionAvailable=1<<0, GesturePinch=1<<1, GestureMovingPinchOpening=1<<2, GestureMovingPinchClosing=1<<3, all tagged "@since 6.2.0"; LEAP_HAND gains "uint32_t flags" at :1705. CFFI exports all four (values 1,2,4,8) and both LeapSetDeviceHints and LeapCheckLicenseFlag. Binding surfaces hand.flags at leapc-python-api/src/leap/datatypes.py:174 (vendored at /Users/joerup/era/leap-input/vendor/LeapMotion-Python-Hyperion, last commit 650784771c69, 2025-10-22).

DEVICE IDENTITY. LeapGetDeviceInfo returns pid=0x3 (eLeapDevicePID_Peripheral, the 2013 v1), caps=0, serial LP20006680004. Service log reports "Camera resolution: 640x240", "Looking for cal: leap".

THE GATE. Gesture detection is not a free-standing field — it is gated behind the "microgestures" DEVICE HINT, which selects a tracking model by tag (libtrack_server strings: HintResolver/src/ModelFilter.cpp, getMatchingModels, "Failed to match required tag: {}", "Model Matched: {} {}"; hint vocabulary includes microgestures, hand_on_object, low_resource_usage, high_hand_fidelity, ultra_performance_mode).

DECISIVE ON-MACHINE TEST (/var/log/ultraleap/tracker_log.txt). Three-way discriminated probe via raw CFFI LeapSetDeviceHints:
  - "bogus_hint_xyz"    -> "Hint bogus_hint_xyz is unknown hint string, ignoring"  (invalid name)
  - "low_resource_usage"-> "HintResolver accepted hints: low_resource_usage"        (CONTROL: mechanism works on this device)
  - "microgestures"     -> "Hint received in core layer: microgestures" then "HintResolver did not accept any hints"
So microgestures is
```

**Corrections:** 1. WRONG SOURCE URL. The cited https://docs.ultraleap.com/api-reference/tracking-api/leapc-guide.html documents NONE of this — no eLeapHandFlag, no LEAP_HAND flags, no gesture detection, no hints. It is a generic LeapC overview. The local header is the only real source for the claim; the relevant vendor page is Hyperion/trackingmodels.html, which contradicts the candidate's usefulness ("HMD only").

2. "No wrapper work needed to read it" — HALF TRUE, AND MISLEADING. Reading is indeed free (hand.flags exists). But ENABLING gesture detection requires LeapSetDeviceHints, which the vendored Python binding does NOT wrap at all (no set_device_hints anywhere in leapc-python-api/src/leap/). That path needs raw CFFI. Moot in the end, since the hint is rejected — but the survey understated the work and missed the hint mechanism entirely, which is the whole gating story.

3. "UNTESTED / unknown macOS viability" — NOW TESTED AND NEGATIVE. The surveyor's 12s probe "saw 1333 frames and zero hands", which is evidence about nothing (no hand was present). My runs captured 2,419 hand-frames with flags always 0. The honest status is no longer "unknown" but "confirmed non-functional on this device".

4. CLAIMED LAYER IS NOT DELIVERED. Filed as "gesture-recognition", but on an LMC v1 this contributes zero gesture recognition. It should be reclassified as a forward-compat capability bit, not a gesture layer. Do not build the pinch/click path on it.

5. LICENSE CHECK IS A FALSE POSITIVE TRAP (new finding, not in survey). LeapCheckLicenseFlag returns enabled=True for arbitrary strings — I got True for "microgestures", "GestureDetection" (not a real flag) and "SetClassifierThresholds". It is not a usable capability probe; anyone gating on it will wrongly conclude gestures are available. Gate on the eLeapHandFlag_GestureDetectionAvailable bit instead.

6. IMPLICIT ASSUMPTION CORRECTED. The flags are not populated by the default tracking model; they require a microgestures-tagged model that ships in the bundle but is incompatible with the v1's "leap" calibration profile. So this cannot be unlocked by config, hints, or the license token (Hyperion_Leap2.tok / install_info mode "Hyperion" are already active) — only by different hardware.


### ISUE/Jackknife — DTW few-shot gesture recognizer — TRIAL

```
FETCHED VIA gh api + raw.githubusercontent, 2026-08-12. Repo is real, not archived, not disabled.

ACTIVITY — "last pushed 2024-01-25" is technically true but materially misleading. Full commit log is SIX commits in nine years:
  2024-01-25 c8bce2e4 Corey Pittman  "Addressing implementation issue for ZNormalize in Mathematics.cs"
  2017-07-26 ac4022c5 / 2017-06-09 x3 / 2017-04-24 80de1517 "Initial commit"
Zero releases, zero tags. 21 stars, 3 forks (two are 2017 mirrors; one is the Python-port fork). This is a frozen CHI-2017 paper artifact with one drive-by bugfix, not a maintained project.

CONTENT VERIFIED IN TREE (1018 blobs, 58 non-dataset). C++ (cpp/jackknife/*.h + jackknife_train.cpp), C# (csharp/Jackknife/*.cs, .sln), JavaScript (js/jackknife/*.js) all present — the tri-language claim is accurate. README's Usage table also advertises Java and Python as "WIP"; neither exists and neither ever shipped.

macOS / arm64 — no platform coupling of any kind. No SIMD, no intrinsics, no threading, no device SDK, no external deps. C++ is header-mostly + CMake; the only vendored code is cpp/evaluate/dirent/dirent.h, a Windows shim macOS doesn't need. JS core is dependency-free (node only for the dataset demo). Nothing to break on Apple Silicon. NOT built on-machine — hence TRIAL not ADOPT.

HYPERION v6 / libLeapC.6 — non-question. Jackknife never links, imports, or references Leap at all. It consumes a generic list of n-dimensional points. Device coupling is zero, so the .5-vs-.6 SONAME issue and Hyperion 6.2 are irrelevant here.

LEAP RELEVANCE IS STRONGER THAN CLAIMED. The repo ships the JK2017 Leap Motion dataset in-tree (datasets/jk2017/leap_motion/{training,sessions}), 9 classes: explode, fist_2_circles, index_2_circles, knock_x3, love, redrum, rock_out, scissors, sideways. Inspected a sample (Sub_U300/rock_out/ex_1.txt): header = gesture name, "120" frames, then 120 "####"-delimited blocks of 21 "x,y,z" lines each. js/evaluate/dataset.js:320-350 flattens each block
```

**Corrections:** Five corrections, two of them serious.

1. LICENSE — the surveyor's "NOASSERTION (check before shipping)" badly understates a blocker. Read the actual LICENSE text: it is the UCF Research Foundation "Florida Public Educational Institution Non-Exclusive Software License." It grants a "royalty-free, non-sublicensable, NON-COMMERCIAL, non-exclusive, ACADEMIC RESEARCH license... with restriction to academic research use only, but including... the rights to use, copy, modify, merge, publish, BUT NOT TO DISTRIBUTE THE WORK." The licensee is defined as "third party Academic Faculty, Researcher(s) and/or Student(s)." Section 5 requires you to publish "Licensed by University of Central Florida Research Foundation, Inc." on your website. The same header is stamped on every source file. For a company building a product, this is not a footnote — it forecloses shipping this code. Era is not an academic licensee.

2. PATENT — missed entirely, and it is named inside the LICENSE itself. Section 2 discloses that the "Synthetic Data Generation of Time Series Data" sub-program is covered by copyright registration 1-4444559149 and patent application 62/362,922. I traced it: provisional 62/362,922 (filed 2016-07-15) → non-provisional 15/651,219 → published US 2018/0018533 A1 → GRANTED as US 10,133,949 B2 on 2018-11-20. Google Patents status line verbatim: "Status Active legal-status Critical Current", anticipated expiration 2037-07-17. Assignee UCF Research Foundation. It claims stochastic resampling / GPSR. Mitigation is clean: GPSR lives only in gpsr() → train() → rejection thresholds. The core recognizer (resample + direction vectors + DTW + correction factors) is the $1 / Penny Pincher / CID lineage — published prior art, not covered by this patent. Skip train() and you never touch the claimed method.

3. "last pushed 2024-01-25" — true, but the surveyor let a pushed_at timestamp stand in for maintenance. Six commits total, five from 2017. Maintainers have sat on a complete Python port PR for 20 months and two correctness bug reports for 13 months. Treat as abandoned-but-working reference code.

4. "~200 lines of Python/NumPy" — optimistic by roughly 1.5x. Measured: ~250-350 lines realistically, and only if you skip train()/GPSR/Distributions.

5. "The paper evaluates on Leap Motion among its device set" — understates it. The repo ships the actual Leap Motion dataset, and the data layout (21 joints × 3 flattened to a 63-D per-frame vector) is a direct match for what your working LeapC 3.12 binding already produces. That is the single strongest argument for this candidate and the surveyor buried it.

Everything else checks out: not archived (true), 21 stars (true), C++/C#/JS reference impls (true), no device or OS dependency (true), algorithm description (accurate).

RECOMMENDED PATH — do not vendor this repo. Reimplement the classifier in Python/NumPy from the CHI 2017 paper (freely available at eecs.ucf.edu/isuelab/research/jackknife/jackknife-final.pdf), using set_ip_defaults (resample 16, radius 2, inner product, no z-normalize), and omit train()/GPSR entirely — that dodges open bug #4, open bug #3, and US 10,133,949 B2 in one move. Get thresholds instead from a held-out enrollment set, or from ISUE/VKM. Gate it on a hold-to-record trigger (pinch or key) rather than continuous spotting for v1; if you later need true continuous segmentation, Machete is the MIT-licensed piece worth porting. Use the in-tree Leap dataset for offline validation only, and have counsel confirm the algorithm-vs-software-license line before any of it ships. Flag this to the user as a licensing decision, not an engineering one.


### casiez/OneEuroFilter — 1€ adaptive smoothing filter — ADOPT

```
REPO IS REAL AND MATCHES THE CLAIM'S HEADLINE NUMBERS (gh api repos/casiez/OneEuroFilter, fetched 2026-08-12): created 2023-08-02, pushed_at 2026-08-05T08:07:59Z, 244 stars, 19 forks, archived=false, disabled=false, open_issues_count=0, default branch main, homepage https://gery.casiez.net/1euro/. Owner is Géry Casiez, first author of the CHI 2012 paper — this is the canonical upstream, not a fork.

COMMIT HISTORY (gh api .../commits): 2026-08-05 "Building image during CI"; 2026-08-05 merge PR #5 "Add Rust implementation" (community, zxq82lm); 2026-02-15 TypeScript constructor-init fix; 2024-09-20/22 two merged PRs from EiraGe (M_PI define, cpp exceptions behind a compiler flag); 2024-08-13 cpp timestamp-regression fix + npm publish; 2023-12-17 "New python version with new methods and doc". Sporadic but genuine maintenance across 3 years, with maintainer-reviewed external PRs.

ISSUE TRACKER IS CLEAN: all 5 issues ever filed (#1–#5) are CLOSED. Zero open issues. None allege the filter is broken; #2 (timestamp ordering) and #3 (M_PI) were real bugs, both fixed and merged. No abandonment signals.

CI IS GREEN ON MAIN: gh api .../actions/runs → 2026-08-05T08:08:01Z "Tests" on main = success. The repo runs a cross-language conformance harness — every implementation must reproduce groundTruth.csv (1200 rows, generated by the reference C++ impl) within 1e-4, enforced by test.py in CI.

NO RELEASES/TAGS on GitHub (0 of each), but the Python artifact ships via PyPI: OneEuroFilter 0.2.1, uploaded 2024-08-13T16:20:28, wheel filename OneEuroFilter-0.2.1-py3-none-any.whl. Note "py3-none-any" — PURE PYTHON, NO COMPILED EXTENSION, so the arm64 question is vacuous.

VERIFIED ON THIS MACHINE (not inferred): `uv pip install OneEuroFilter` into a 3.12 venv → installed oneeurofilter==0.2.1, resolved 1 package with ZERO transitive dependencies. Import succeeded reporting py 3.12.13 / machine arm64. Source (python/OneEuroFilter/OneEuroFilter.py, 8535 bytes) imports only stdlib `math`.


```

**Corrections:** Five corrections; none change the ADOPT verdict.

1. CLAIMED LAYER IS WRONG. "gesture-recognition" mislabels it. The 1€ filter recognizes nothing — it is a scalar signal-conditioning stage. In the pipeline it belongs strictly between the LeapC frame read and everything downstream (cursor mapping, pinch/grab state machines, velocity thresholds). Smoothing AFTER a gesture decision is useless; smoothing BEFORE it is what stops jitter from chattering your pinch detector. Call it "signal conditioning / pre-processing".

2. "TWO TUNABLE PARAMETERS" IS INCOMPLETE AS AN API DESCRIPTION. The paper's tuning story is genuinely two knobs (mincutoff, beta), and that survives. But the Python constructor is OneEuroFilter(freq, mincutoff=1.0, beta=0.0, dcutoff=1.0): `freq` is a REQUIRED positional arg with a >0 validator that raises ValueError, and it is load-bearing — it sets the alpha for the very first sample and for every sample where a timestamp is absent or non-increasing. There is also a fourth knob, dcutoff. Budget for three constructor args, not two.

3. "~40 LINES OF PYTHON" UNDERSTATES THE SHIPPED MODULE. The algorithm core is indeed ~40 lines, but the shipped file is 8535 bytes / ~200 lines with docstrings, setters, and reset(). "No dependencies" is exactly right (stdlib math only) — that part of the claim is confirmed.

4. "ACTIVELY MAINTAINED (pushed 2026-08-05)" IS TECHNICALLY TRUE BUT MISLEADING ABOUT THE PYTHON PATH. The 2026-08-05 push was a community-contributed RUST implementation plus a CI Dockerfile tweak — it did not touch Python. The Python implementation's last substantive change was 2023-12-17, and PyPI has been frozen at 0.2.1 since 2024-08-13. This is fine (the algorithm is frozen by the 2012 paper and CI proves conformance), but do not expect Python-side responsiveness. The repo is a stable multi-language reference, not a project under active development.

5. LICENSE PROVENANCE IS PER-FILE, NOT REPO-LEVEL. GitHub reports license: null and there is NO LICENSE file at the repo root; the BSD-3-Clause grant lives in per-source-file headers and in a python/LICENSE. PyPI metadata likewise has an empty license field, carrying only the "OSI Approved :: BSD License" classifier. Usable, but cite the file header, not "the repo is BSD".

TWO ON-MACHINE FINDINGS THE SURVEYOR DID NOT MENTION, both of which will bite this project specifically:

A. TIMESTAMP 0.0 IS SILENTLY MISHANDLED. Line: `if self.__lasttime and timestamp and timestamp>self.__lasttime:`. That is a truthiness test, so a timestamp of exactly 0.0 is falsy and the frequency update is skipped. I reproduced it: feeding signal [0,1,2,3,4,5] at a true 10 Hz with timestamps starting at 0.0 gives [0.0, 0.077169, 1.172938, 2.268905, 3.329755, 4.362363], while the identical series offset by +1000 s gives [0.0, 0.46546, 1.286015, 2.274903, 3.309477, 4.342831] — different output for identical dt. Consequence for this build: do NOT pass elapsed-since-start seconds. Pass an absolute clock — time.monotonic(), or the LeapC frame's own timestamp — so the first value is never 0.0.

B. reset() DOES NOT RESTORE THE CONSTRUCTOR FREQUENCY. OneEuroFilter.reset() clears the two low-pass states and __lasttime but leaves __freq at whatever value the last timestamp pair derived. After a tracking dropout and reset, the first post-reset sample is filtered using the stale pre-dropout rate. Impact is one sample and only matters if the frame rate shifted; construct a fresh filter on hand-lost if you care.

ALSO WORTH KNOWING: the filter is SCALAR-ONLY. There is no vector API in the Python package. Palm position needs three independent instances (x, y, z), and per-joint smoothing needs one per axis per joint. Each instance is independent state — cheap (0.74 µs/call) but you own the bookkeeping.


### ultraleap/UnityPlugin — HandPoseDetector (static pose matching) — ADOPT (as algorithm source / design reference — not as an installable dependency)

```
REPO LIVENESS (GitHub API, fetched 2026-08-12)
- ultraleap/UnityPlugin: pushed_at 2026-07-07T15:07:38Z, updated_at 2026-08-03. archived=false, disabled=false. 589 stars, 174 forks, 4 open issues. License Apache-2.0 at root AND at Packages/Tracking/LICENSE.md (verified the per-package file, not just the repo-level badge — the Tracking package that contains the detector is genuinely Apache-2.0, so reuse/porting is clean).
- Recent develop commits are real engineering, not badge churn: 2026-07-07 "Merge PR #1713 rcb/connection-rework", 2026-07-07 "Update changelog for LeapC 7.9.0.102 native fixes", 2026-06-29 "Shut down the LeapCSharp background threads reliably on editor reload and quit", 2026-06-10 "Fixes for deprecated APIs ... (Unity 6.4)".
- Only 2 genuine open issues: #1715 "Drop Support for Unity 2023.2" (2026-06-10), #1689 "Fiducial tracking orientation is flipped in desktop mode" (2025-06-15). Neither touches pose detection.

THE FILE ITSELF IS MAINTAINED (the key anti-skepticism check — an active repo can still carry a 2023 fossil)
- git log for Packages/Tracking/Core/Runtime/Scripts/HandPoses/HandPoseDetector.cs on develop: 2026-02-23 "Fix formatting errors"; 2025-11-12 "Adding in support for pose proximity rules"; 2024-07-16 namespace rework; 2024-05-14 "initial bone and finger simplification"; then a 2023-03 burst. So the detector received a real feature in Nov 2025 and was touched in Feb 2026. Not abandoned.
- Corroborated by CHANGELOG 7.3.0 (25/02/2026): "Added support for proximity rules in pose detection", "Added support for pose detection to require that both hands are in the target pose", "Added optional argument to AssignBestLeapProvider ... Fixes a potential pose detection bug."

ALGORITHM CLAIMS — verified line-by-line against develop HEAD (760 lines, downloaded)
- L456-457: `Vector3 activeRotEuler = (Quaternion.Inverse(lastBoneRotation) * activeBoneRotation).eulerAngles;` and the same for the serialized template. Relative bone rotations confirmed
```

**Corrections:** Six corrections. None invalidate the recommendation; three are load-bearing for the port.

1. WRONG BRANCH IN THE URL. The repo's default branch is `develop`, not `main`. The candidate URL (/blob/main/...) does resolve — `main` exists and has the file — but `git compare main...develop` reports develop is 23 ahead / 1 behind. Read and port from `develop`, or you will copy a stale detector missing the recent connection/namespace work.

2. "Last activity: pushed 2026-07-07" conflates commit activity with a release. That date is a merge on `develop`. The last TAGGED RELEASE is com.ultraleap.tracking/7.3.0 on 2026-02-25 — roughly six months stale. Release cadence is slow (7.2.0 Jan 2025, 7.1.0 Sep 2024). Repo activity ≠ shipping cadence. Immaterial here since we vendor an algorithm rather than consume a package.

3. "reduced to Euler X/Y" is true but imprecise, and porting it as stated produces a detector that is too strict. X is checked on EVERY compared bone; Y is checked ONLY on PROXIMAL bones, where the code comments it as abduction/splay: `if (serializedHandBone.Type == Bone.BoneType.PROXIMAL) // Proximal also uses Y rotation`. Intermediate and distal are X-only. Z is never used anywhere.

4. "Deliberately ignores metacarpals" understates their role. Metacarpals are skipped from COMPARISON but are retained as the rotation REFERENCE: the `continue` at L431-436 assigns `lastBoneRotation = activeHandBone.Rotation` before skipping, so the proximal bone's relative rotation is measured against the metacarpal, not against the palm. The chain is seeded from `playerHand.Rotation` (palm) at the top of each finger loop. A port that simply drops metacarpals from the array will compute every proximal angle against the wrong reference frame.

5. Hysteresis is not confined to bone rotations, as the claim implies. The direction rules add a hardcoded 5° (`hysteresisToAdd = 5f`, L662) and the proximity rules add a hardcoded 0.005 m (L583) once the pose is detected — separate literals from the scriptable object's `hysteresisThreshold`.

6. "The algorithm ports directly" is optimistic on one specific point the surveyor did not flag. Unity's `.eulerAngles` returns 0–360°, and the difference is taken with `Mathf.DeltaAngle` (L744-745), which yields the shortest SIGNED angular difference. A naive Python port doing plain subtraction on Euler angles breaks at the 0/360 wraparound and will drop poses intermittently. Additionally, Unity is left-handed Y-up with ZXY Euler order while LeapC is right-handed — so you must fix your own Euler convention, and the numeric thresholds in Ultraleap's shipped .asset templates (Fist, OK, Point, Horns, Open Palm, Thumbs Up) will NOT transfer. This is harmless in practice because you record your own templates with the same code that reads them, but it means the shipped pose assets are worthless to us and the thresholds must be re-tuned from scratch.

MAINTENANCE CAVEAT NOT MENTIONED. The README states: "Our Discord Server, Github Discussions and Developer Forum are now read only." Ultraleap has closed its community support channels. The low open-issue count (2) partly reflects closed intake rather than a defect-free codebase. Expect no community help; the code is the documentation.


## Lens: llm-computer-use-bridge

The decisive finding is trycua/cua's `cua-driver`, and I verified it live on your machine rather than trusting the README: `uv pip install cua-driver` into a Python 3.12 venv yielded v0.19.3 (macosx_13_0_universal2 wheel), the daemon started, and `get_screen_size` returned exactly 1512x982 @ 1.0 — matching your ground truth — while `get_accessibility_tree` enumerated real running apps. It exposes ~60 MCP tools including a semantic AX tree, `invoke_menu`, `verify_state`, `replay_trajectory`, and critically `start_session`, which gives the agent its own color-coded cursor and delivers clicks/typing through AX in the background without moving the human cursor or stealing focus. That last property is the whole architecture: it is the only piece in this ecosystem that lets an agent act while a Leap-driven cursor is simultaneously live, because everything else (pyautogui, CGEventPost, AppleScript) fights you for the one system cursor. For the key question — the clean split is a two-tier bus: continuous pointing/scrolling goes straight to CGEventPost at frame rate and must never touch a model (an LLM round-trip is 1–3 s against your 9 ms frame budget), while discrete committed gestures emit a typed intent token that a dispatcher resolves either deterministically (a named cua-driver tool call, or an OpenAdapt compiled workflow at zero model calls) or generatively (Claude Agent SDK talking to `cua-driver mcp`) for open-ended tasks. Anthropic's own macOS-native quickstart exists and is real, but it is pyautogui-based, has no programmatic task API, and its README strongly discourages running it outside a disposable VM — so it is a design reference here, not the runtime.

| Candidate | Layer | Verdict | Last activity |
|---|---|---|---|
| [trycua/cua — cua-driver](https://github.com/trycua/cua/tree/main/libs/cua-driver) | action-injection | **ADOPT** | 2026-08-12 (today) — repo pushed 2026-08-12T21:59Z; nightly cua-driver-rs v0.19.4 published 2026-08-12T15:44Z; PyPI/npm stable 0.19.3 |
| [trycua/cua — Agent SDK + Sandbox + Lume](https://github.com/trycua/cua) | orchestration | **TRIAL** | 2026-08-12 — sandbox-v0.2.0 (2026-08-11), lume-v0.5.3 (2026-08-11), fleet-v0.1.8 (2026-08-11) |
| [Anthropic computer-use-best-practices quickstart](https://github.com/anthropics/anthropic-quickstarts/tree/main/computer-use-best-practices) | end-to-end | **TRIAL** | 2026-08-06 (repo push); computer_use tool version computer_use_20251124 |
| [Anthropic computer-use-demo (anthropic-quickstarts)](https://github.com/anthropics/anthropic-quickstarts/tree/main/computer-use-demo) | end-to-end | **—** | 2026-08-06 (parent repo push) |
| [OpenAdaptAI/OpenAdapt](https://github.com/OpenAdaptAI/OpenAdapt) | orchestration | **TRIAL** | 2026-08-12 (today); PyPI openadapt 1.12.1, requires >=3.10,<3.13 |
| [simular-ai/Agent-S (S3)](https://github.com/simular-ai/Agent-S) | orchestration | **—** | 2026-08-01; PyPI gui-agents 0.3.2, requires >=3.9,<=3.12 |
| [steipete/Peekaboo](https://github.com/steipete/Peekaboo) | action-injection | **—** | 2026-08-12 (today); 4,983 stars, 3,187 commits, MIT |
| [CursorTouch/MacOS-MCP](https://github.com/CursorTouch/MacOS-MCP) | transport | **—** | 2026-08-12 (today); 147 stars, MIT |
| [steipete/macos-automator-mcp](https://github.com/steipete/macos-automator-mcp) | transport | **—** | 2026-08-10; 866 stars, MIT, TypeScript |
| [mediar-ai/MacosUseSDK + mcp-server-macos-use](https://github.com/mediar-ai/MacosUseSDK) | capture | **—** | 2026-04-26 — roughly 3.5 months stale as of today (SDK 204 stars MIT; MCP server 348 stars) |
| [steipete/AXorcist](https://github.com/steipete/AXorcist) | capture | **—** | 2026-08-12 (today); 316 stars, MIT |
| [eeejay/pyax](https://github.com/eeejay/pyax) | capture | **—** | 2026-02-28; only 15 stars, MIT |
| [mediar-ai/screenpipe](https://github.com/mediar-ai/screenpipe) | capture | **—** | 2026-08-12 (today); 20.9k stars, NOASSERTION license |
| [OpenInterpreter/open-interpreter](https://github.com/openinterpreter/openinterpreter) | orchestration | **—** | 2026-08-08; 68k stars, Apache-2.0 |
| [OthersideAI/self-operating-computer](https://github.com/OthersideAI/self-operating-computer) | orchestration | **—** | 2025-09-19 — roughly 11 months stale, the most stagnant candidate here |
| [e2b-dev/desktop](https://github.com/e2b-dev/desktop) | orchestration | **—** | 2026-08-12 (today); 1,449 stars, Apache-2.0 |
| [macOS26/Agent](https://github.com/macOS26/Agent) | end-to-end | **—** | 2026-08-05; 565 stars, MIT |

### trycua/cua — cua-driver — ADOPT

```
REPO LIVENESS (GitHub API, not scraped pages)
- repos/trycua/cua: pushed_at 2026-08-12T21:59:14Z (today), archived=false, MIT, 21,279 stars, 610 open issues, default branch main. Exactly matches the surveyor's claimed timestamp.
- libs/cua-driver exists with rust/ python/ typescript/ contract/ docs/ tests/ wayland-helper/. Last 10 commits touching that path all 2026-08-11..08-12, e.g. 0813659a "feat: add persistent Driver and Lume release channels" (2026-08-12T14:36Z), d5096871 "fix(cua-driver): preserve direct MCP session ownership (#3079)". This is a daily-active subtree, not a dumped prototype.
- Releases: nightly-cua-driver-rs-v0.19.4-nightly.20260812 published 2026-08-12T15:44:37Z; cua-driver-rs-v0.19.3 2026-08-10T13:41Z. PyPI cua-driver 0.19.3 uploaded 2026-08-10T13:43Z; npm @trycua/cua-driver 0.19.3 published 2026-08-10T13:43Z with per-platform optionalDeps incl. @trycua/cua-driver-darwin-arm64.

ARM64 macOS — VERIFIED ON THIS MACHINE
- Found an existing uv-cached install: /Users/joerup/.cache/uv/archive-v0/Nh2rX9a9S9zxr1kj/cua_driver (written 2026-08-12 15:30), plus an empty socket dir /Users/joerup/Library/Caches/cua-driver — corroborates the surveyor's earlier run.
- `file` on cua_driver/bin/cua-driver and libcua_driver_sdk.dylib: "Mach-O universal binary with 2 architectures [x86_64][arm64]". Native arm64 slice present. `cua-driver --version` -> 0.19.3.
- PyPI wheel is cua_driver-0.19.3-py3-none-macosx_13_0_universal2.whl, requires_python >=3.10. I installed it into a FRESH uv --python 3.12 venv successfully. This matters for the Leap work: the Ultraleap CFFI module is CPython-3.12-only, and cua_driver imports fine in that same 3.12 interpreter, so one venv can host both.

LIVE TOOL EXECUTION (I ran these, not the surveyor)
- Started `cua-driver serve`; `cua-driver status` -> running, pid 45474, permission mode standard.
- call get_screen_size -> {"width":1512,"height":982,"scale_factor":1.0} — exact match to ground truth.
- call get_cursor_position -> re
```

**Corrections:** Four corrections, one of them material to the Leap build.

1. MATERIAL — move_cursor is far too slow to be the Leap cursor transport. The surveyor listed it as an available action and stopped there. I benchmarked it:
   - via `cua-driver call` CLI: p50 ~50 ms/call (min 49.3, max 65.8) — ~20 Hz ceiling, and that includes process spawn.
   - via the in-process Python UniFFI SDK (EMBEDDED, no daemon), 300 iterations: min 118.7 ms, p50 166.9 ms, p95 180.6 ms, max 245.1 ms — a ~6 Hz ceiling. The in-process path is SLOWER than the CLI.
   The cause is by design: move_cursor is a glided/animated agent cursor. SetAgentCursorMotionInput exposes glide_duration_ms, spring, arc_size, arc_flow, turn_radius, dwell_after_click_ms. My cursor-restore call visibly landed short of its target mid-glide. Against a 111 fps Leap stream (measured ground truth) this would lag by 150+ ms per update. Conclusion: drive continuous cursor motion with raw CGWarpMouseCursorPosition/CGEventPost (sub-ms, and Accessibility is already granted to the terminal per ground truth), and use cua-driver for the discrete semantic layer — AX-element clicks, invoke_menu, launch_app, get_window_state, verify_state, and the LLM agent loop over MCP.

2. MATERIAL — the existing terminal Accessibility grant does NOT carry to cua-driver. Ground truth says "macOS Accessibility permission is ALREADY granted to the terminal." When I launched `cua-driver serve` from this shell it printed a TCC gate: "Missing TCC grant(s) for this process: Accessibility, Screen Recording," and `call check_permissions` returned {"accessibility":false,"screen_recording":false,"source":{"attribution":"caller"}}. Its own note: "These booleans reflect the TCC identity of the app that launched this process ... NOT an installed CuaDriver app bundle." Read-only/warp tools (get_screen_size, get_cursor_position, list_apps, get_accessibility_tree, move_cursor) work ungranted; AX-dependent tools (get_window_state, type_text, verified click, zoom, window screenshots) will not. `click` did post but returned effect:"unverifiable". The README further states that spawning raw `cua-driver serve` outside CuaDriver.app is unsupported — production use requires installing CuaDriver.app and running `cua-driver permissions grant`, or the embedded-host path where the owning app's grants are inherited.

3. Tool count overstated: "~60 tools" — `list-tools` on this machine printed 54. The checked-in contract/manifest.json declares only 25 and is flagged experimental:true, contract_version 0.7.0, so do not treat that manifest as the tool inventory.

4. Minor conflation: the surveyor attributed "AX tree with structured element array" to get_accessibility_tree. get_accessibility_tree actually returns a lightweight desktop snapshot (running apps + visible windows + bounds/z-order/pid). The structured `elements` array comes from get_window_state, which walks one app's AX tree — and that one is gated on the Accessibility grant that is currently false.

Also worth flagging (not an error, a naming trap for whoever installs it): the npm package is @trycua/cua-driver, not @trycua/driver (the latter 404s). And every cua-driver-rs GitHub release, including 0.19.3, is tagged prerelease=true; the "stable" designation exists only on PyPI/npm.


### trycua/cua — Agent SDK + Sandbox + Lume — TRIAL

```
ALIVE — not remotely abandoned. GitHub API on trycua/cua: `pushed_at` 2026-08-12T21:59:14Z (today), `archived: false`, `disabled: false`, MIT, 21,279 stars, 610 open issues, created 2025-01-31, default branch `main`. Ten most recent commits all land 2026-08-11/12 (e.g. "feat(sandbox)!: boot the same Windows containerDisk locally and in Fleet cloud", "docs(cua-driver): add Grok Bot integration guide (#3112)"). Multi-author (r33drichards, Francesco Bonacci). Zero staleness signal.

RELEASE TAGS — all three surveyor claims confirmed verbatim via /releases: `sandbox-v0.2.0` 2026-08-11T06:40:01Z, `lume-v0.5.3` 2026-08-11T12:24:33Z, `fleet-v0.1.8` 2026-08-11T07:43:44Z. Cadence is weekly-or-faster per product (sandbox went 0.1.21→0.2.0 between 2026-08-02 and 2026-08-11). Nightlies cut today: `nightly-lume-v0.5.4-nightly.20260812`, `nightly-cua-driver-rs-v0.19.4-nightly.20260812`.

API SHAPE — confirmed verbatim in README, not paraphrased: `async with Sandbox.ephemeral(Image.linux()) as sb:` with the comment `# or .macos() .windows() .android()`. Lume described verbatim as "Create and manage macOS/Linux VMs with near-native performance on Apple Silicon using Apple's Virtualization.Framework." cua-bench provides "Benchmarks & RL Environments" against OSWorld, ScreenSpot, Windows Arena. Monorepo `libs/` contains cua-bench, cua-driver, cua-driver-fixtures, cuabot, fleet, kasm, lume, lumier, python, qemu-docker, typescript, xfce/xfce-cua.

ARM64-macOS CAPABLE — yes, first-class, with shipped binaries. `cua-driver-rs-v0.19.3` assets include `cua-driver-rs-0.19.3-darwin-arm64.tar.gz`, `-darwin-universal.tar.gz`, and a Python wheel `cua_driver-0.19.3-py3-none-macosx_13_0_universal2.whl`, plus `install.sh`. Lume is Swift-on-Virtualization.framework, i.e. Apple-Silicon-native by construction.

LOCAL DESKTOP PATH — surveyor's caveat is correct and confirmed by README: "Cua Drivers ... Drive native desktop apps in the background. Agents click, type, and verify without stealing the cur
```

**Corrections:** Four corrections, one of them load-bearing for this machine.

1. PYTHON VERSION CEILING — the surveyor never checked it, and it is the single most important compatibility fact. Every cua Python package pins `<3.14`: cua-agent 0.8.4 `<3.14,>=3.11`, cua-computer 0.5.19 `<3.14,>=3.12`, cua-sandbox 0.2.0 `<3.14,>=3.11`, cua-core 0.3.1 `<3.14,>=3.11`. This is a fortunate convergence: the system default python3 3.14.6 is excluded by cua for the same reason it is excluded by the Leap bundled CFFI (`_leapc_cffi.cpython-312-darwin.so`, 3.12-only). The existing uv 3.12 venv satisfies both, so Leap bindings and cua can live in ONE interpreter. Had cua required 3.13+, the whole integration would have needed a two-process split.

2. "Last activity 2026-08-12" is true for the repo but NOT uniformly true across the halves, and the surveyor's framing hides this. The sandbox/driver/fleet/lume half ships weekly; the *agent SDK* half the candidate leads with is materially staler on PyPI — cua-agent last published 2026-06-24, cua-computer 2026-06-18, cua-core 2026-04-15. That is ~7 weeks to ~4 months. The repo's own description has been rewritten to "Scale computer-use 2.0 with open-source drivers, cross-OS fleets, and benchmarks" — drivers/fleets/benchmarks, no longer agent-loop-first. Treat "Agent SDK" as the legacy positioning, not the current center of gravity.

3. "cua-driver-rs" releases are flagged **Pre-release** on GitHub (0.19.0 through 0.19.4-nightly), which reads as unstable and would justify a REJECT on a shallow look. It is an artifact, not a quality signal — the release body states it explicitly: "GitHub's label is used only to keep this monorepo's repository-wide 'Latest' pointer from switching between independently released products. A plain Cua Driver SemVer is a stable release; npm and PyPI publish it on their normal stable channels." Do not down-rank on the pre-release badge.

4. The candidate says macOS viability "yes" without flagging a design-intent mismatch with the Leap goal. cua-driver's headline property is that it drives apps *without moving the real cursor or taking focus* — the deliberate opposite of a hand-tracked pointer, whose entire purpose is to move the visible system cursor. (A visible-pointer mode does exist and is e2e-tested — issue #2879 "require visible pointer and badge on Linux, Windows, and macOS" — so this is a default to override, not a wall.) Consequence for architecture: cua-driver is per-call RPC over MCP/stdio and is the wrong layer for 111 fps pointer updates; keep raw cursor motion on direct CGEventPost (already verified working) and use cua only for the semantic tier — "click that button", "run this agent action".

Why TRIAL rather than ADOPT: the project is alive and genuinely macOS-arm64-viable, but as scoped by the candidate (Sandbox + Lume + fleet orchestration) it is not directly usable for driving this desktop — that half targets VMs and is largely irrelevant to the stated goal. The directly usable piece is cua-driver, a different component from the one this candidate describes. Adopt-worthy only after an on-machine trial of `cua-driver` specifically: install via install.sh, confirm the darwin-arm64 binary runs under Hyperion's already-granted Accessibility permission, and confirm visible-pointer mode can be forced. The Sandbox/Lume/fleet half should be scored separately and, for this goal, deprioritized.


### Anthropic computer-use-best-practices quickstart — TRIAL

```
REPO IDENTITY (candidate URL is stale): `anthropics/anthropic-quickstarts` 301-redirects to `anthropics/claude-quickstarts` (GitHub API repo id 849553306). MIT, not archived, not disabled, 17,425 stars, 195 open issues, created 2024-08-29, `pushed_at` 2026-08-06T17:17:51Z, default branch `main`. The directory `computer-use-best-practices` exists at the repo root.

REAL LAST ACTIVITY FOR THIS PATH: `gh api "repos/anthropics/claude-quickstarts/commits?path=computer-use-best-practices&per_page=15"` returns exactly ONE commit: `b03d42cc`, 2026-05-13T23:11:24Z, "Add computer-use-best-practices quickstart (#402)". The subproject has never been modified since it landed — ~3 months static. The 2026-08-06 push date is repo-level (other quickstarts), not this directory.

OPEN ISSUES INDICATING BREAKAGE: none. `search/issues?q=repo:anthropics/claude-quickstarts+computer-use-best-practices` returns total_count=3, all unrelated or the merged PR itself: #402 (closed, the adding PR), #308 (open, 2025-11-23, Linux VM guide for the *other* computer-use-demo), #137 (closed, 2024-10-29, predates this by 18 months). Zero bug reports filed against it — which also means near-zero external usage signal.

macOS / arm64 VIABILITY — VERIFIED ON THIS MACHINE, not inferred: `pyproject.toml` sets `requires-python = ">=3.11"` and `[tool.uv] environments = ["sys_platform == 'darwin'"]` with the comment "macOS-only project; don't resolve Linux-only transitive deps (python3-xlib)". Every one of the 70 lines in `requirements.txt` carries `; sys_platform == 'darwin'`. I ran a real resolution with uv 0.11.32 (aarch64-apple-darwin): `uv venv --python 3.12` + `uv pip install --dry-run -r requirements.txt` → "Resolved 70 packages / Would install 70 packages", zero errors, zero conflicts. Repeated on Python 3.14 → also 70/70 clean. So arm64 wheels exist for the whole tree (numpy 2.4.3, pyarrow 23.0.1, pillow 12.1.1, pyobjc-core/cocoa/quartz 12.1, playwright 1.58.0, pyautogui 0.9.54, anthropic 0.93.0, stre
```

**Corrections:** Four corrections, one of them material.

1. WRONG TOOL VERSION STRING. The surveyor claims "computer_use tool version computer_use_20251124". No such string exists in the repo. `constants.py:64-65` reads `HOSTED_COMPUTER_TOOL_TYPE = "computer_20250124"` and `COMPUTER_USE_BETA = "computer-use-2025-01-24"`. The other beta strings are `ADVISOR_BETA = "advisor-tool-2026-03-01"` (constants.py:298) and `COMPACTION_BETA = "compact-2026-01-12"` (constants.py:299). "computer_use_20251124" appears to be fabricated or garbled — treat it as a hallucination marker on the rest of that survey line.

2. MISLEADING LAST-ACTIVITY DATE. "last activity: 2026-08-06 (repo push)" is a repo-level timestamp attributed to a subdirectory that has not been touched since 2026-05-13 (single commit b03d42cc). The distinction matters: the surrounding repo is alive, this subproject is frozen.

3. STALE URL / REPO NAME. The repo was renamed `anthropic-quickstarts` → `claude-quickstarts`. The given URL still resolves via GitHub's redirect, but the canonical path is https://github.com/anthropics/claude-quickstarts/tree/main/computer-use-best-practices.

4. "LAYER: end-to-end" IS WRONG FOR THIS PROJECT'S GOAL. It is end-to-end for *LLM-driven* computer use, but it contributes nothing to the gesture half of the stack. There is no input-source abstraction, no device plugin seam, and no Leap coupling of any kind — adding a `Tool` subclass is trivial (`tools/base.py` `Tool`/`ToolCollection`), but hand tracking is an input source, not a tool, so there is no natural insertion point. Correct layer label: "agent loop + macOS actuation", roughly the top third of the intended system.

Claims that held up exactly as stated: macOS-native with no Docker; explicitly macOS-only for the stated reasons (key handling, pyautogui backend, sandbox-exec); the full tool roster (computer/computer_batch, browser/browser_batch, editor, sandboxed bash+python via sandbox-exec, open_application, optional server-side advisor); image sizing/pruning, prompt caching, server-side compaction, batched tool calls, and trajectory recording to runs/<timestamp>/.

Why TRIAL and not ADOPT: it is alive-by-provenance (first-party Anthropic, MIT, no open defects) and macOS/arm64-viable (proven by resolution on this machine), but it fails "directly usable" for the stated goal on three counts — it is self-described as a read-and-modify reference implementation rather than a library, it carries an explicit vendor recommendation to run only in a VM that the Leap hardware requirement rules out, and it does not address the gesture-capture half at all. I did not execute the agent loop (needs an ANTHROPIC_API_KEY, a Screen Recording grant, and `playwright install chromium`), so end-to-end function on this machine is resolved-but-unproven. Recommended trial: install into the existing Leap 3.12 venv, grant Screen Recording, run one scripted task, and confirm the pyautogui/CGEvent actuation path does not fight a Leap-driven CGEventPost controller.


### Anthropic computer-use-demo (anthropics/claude-quickstarts, formerly anthropic-quickstarts) — REJECT

```
ALIVE, BUT WRONG TARGET FOR THIS GOAL — and superseded for macOS by a sibling quickstart in the same repo that the surveyor missed.

REPO IDENTITY / LIVENESS (gh api, authed as joerup, 2026-08-12)
- The URL given redirects: `api.github.com/repos/anthropics/anthropic-quickstarts` returns HTTP 301 → `repositories/849553306`, whose `full_name` is now **anthropics/claude-quickstarts**. Not archived, not disabled, 17,425 stars, 195 open issues, default branch `main`, repo `pushed_at` 2026-08-06T17:17:51Z.
- Subproject-scoped history (`commits?path=computer-use-demo`) — last 6 commits:
  2026-05-28 f37f1685 "Add adaptive thinking support to the computer-use demo (#411)"
  2026-05-13 b03d42cc "Add computer-use-best-practices quickstart (#402)"
  2026-02-05 4b2549e8 text_editor_20250728 exclusively
  2025-12-10 ee3afd9b left_click_drag start_coordinate
  2025-12-06 ab002f0a Opus 4.5 in README
  2025-11-24 5a3c6f8f "Adds zoom tool for Opus 4.5 (#309)"
  → real last activity on THIS subproject is 2026-05-28, ~2.5 months stale, not 2026-08-06.
- Published image is current with the code and multi-arch: ghcr.io/anthropics/anthropic-quickstarts:computer-use-demo-latest is an OCI index with linux/amd64 AND linux/arm64 manifests; the arm64 config blob has `created: 2026-05-28T21:05:52Z, architecture: arm64, os: linux`. It will run natively on the M5 Pro — no Rosetta/qemu emulation.

WHAT IT ACTUALLY CONTROLS (Dockerfile + tools/computer.py)
- `FROM docker.io/ubuntu:22.04` + xvfb, xterm, xdotool, scrot, imagemagick, mutter, x11vnc, noVNC v1.5.0, firefox-esr, libreoffice, tint2; entrypoint `./entrypoint.sh`; ports 5900/8501/6080/8080.
- computer.py builds every action as `DISPLAY=:{DISPLAY_NUM} xdotool ...` (`self._display_prefix = f"DISPLAY=:{self.display_num} "`). It drives the container's X11 display. There is no macOS backend — no CGEventPost, no pyautogui, no cliclick. The surveyor's "controls the container, not your Mac" is exactly right.

TOOL VERSION / ZOOM CLAIM — CONFIRMED

```

**Corrections:** Four corrections, one addition:

1. WRONG REPO NAME/URL. The repo was renamed `anthropics/anthropic-quickstarts` → **`anthropics/claude-quickstarts`** (GitHub API returns 301 on the old path; it still redirects, so the link works, but the canonical name is wrong). The ghcr image tag still uses the old org path (`ghcr.io/anthropics/anthropic-quickstarts:computer-use-demo-latest`) — do not "correct" that string.

2. LAST-ACTIVITY DATE INFLATED. "2026-08-06 (parent repo push)" is a repo-wide figure. The computer-use-demo subtree's last commit is **2026-05-28** (f37f1685). The surveyor correctly flagged it as parent-repo push, but the number should not be read as this project's liveness — a 17k-star multi-project monorepo pushes constantly for unrelated demos.

3. "macOS viability: no" IS RIGHT FOR THE WRONG REASON — and understates half of it. It is not that the image can't run on this Mac: the published image is a genuine multi-arch OCI index with a **linux/arm64** manifest built 2026-05-28, so it runs natively on the M5 Pro with no emulation. The disqualifier is purely the control surface — every action is `DISPLAY=:N xdotool ...` against the container's Xvfb, so it can never touch the host desktop. State it as "runs fine on this hardware, controls the wrong machine."

4. TOOL-VERSION STRING IS THE DEMO'S LABEL, NOT THE API'S. `computer_use_20251124` is this repo's internal `ToolVersion` literal. On the wire the tool `type` is **`computer_20251124`** and the beta header is **`computer-use-2025-11-24`**. The claim is accurate within the demo's vocabulary; don't carry `computer_use_20251124` into API code.

5. ADDITION — the survey missed the sibling that actually fits. `computer-use-best-practices/` was added to the same repo on 2026-05-13 (#402) and is explicitly **macOS-native, no container**, pyautogui-based, with Screen Recording/Accessibility preflight checks and a zoom-capable computer tool. The computer-use-demo README itself links to it. It should be surveyed and given its own verdict; on current evidence it is the TRIAL candidate for the LLM-computer-use layer of this system, and this containerized demo should be dropped from consideration as anything but a code reference.

6. MINOR — "the original containerized reference agent" is accurate but the model support is stale: default `claude-opus-4-8`, no Opus 5 / Sonnet 5 / Fable 5 in the model table, and unlisted models silently fall back to the 2025-04-29 tool version with thinking off (losing zoom).


### OpenAdaptAI/OpenAdapt — TRIAL

```
ALIVE — confirmed, not stale.
- `gh api repos/OpenAdaptAI/OpenAdapt`: pushed_at 2026-08-12T10:24:18Z, updated_at 2026-08-12T20:50:03Z, archived=false, MIT, 1676 stars / 262 forks. Latest human commit c6fbd753 "fix(deps): bump h2 to 4.4.1" 2026-08-11; releases v1.12.1 (2026-08-11), v1.12.0 (08-05), v1.11.0 (08-02), v1.10.x (07-27..08-02).
- Engine repo OpenAdaptAI/openadapt-flow pushed 2026-08-12T22:31:13Z, MIT, public.
- PyPI: openadapt 1.12.1 uploaded 2026-08-11T19:47:30, requires_python "<3.13,>=3.10", classifiers 3.10/3.11/3.12. openadapt-flow 1.31.0 (2026-08-09). openadapt-capture 1.2.2 (2026-07-28).
- Repo description is verbatim the claim: "Compile a demonstrated GUI workflow into a deterministic, locally executable program. Zero model calls on healthy runs; governed repair; halts instead of guessing. Launcher for openadapt-flow: pip install openadapt".

ARM64 macOS — PROVEN ON THIS MACHINE, not inferred.
- uv venv 3.12.13 arm64 at /private/tmp/claude-501/-Users-joerup-era-era-memory-evals/1f99f28d-32a3-423c-93b9-1778e24655e6/scratchpad/oa-venv; `uv pip install "openadapt[capture,macos]"` then `[browser]` succeeded, no source builds, no arch failures. All deps pure-Python + pyobjc-framework-{quartz,cocoa,applicationservices} (arm64-native wheels).
- `openadapt version` → openadapt 1.12.1, openadapt-flow 1.31.0, openadapt-capture 1.2.2. `openadapt doctor` → "Platform: Darwin 25.5.0", all core packages OK.
- CI matrix (.github/workflows/main.yml L26-32) runs ubuntu-latest AND macos-latest (= arm64) on py3.10/3.11/3.12.
- FULL END-TO-END RUN: `openadapt quickstart` completed all 5 phases and printed "VERIFIED in 3.7s; 0 model calls; the system of record holds 1 record(s)", "model calls 0", "effects 2/2 confirmed at evidence tier 1", bundle digest e789fb5a71153b7bf1c943eecfc834c17256fc623b45c51dd4d95099cf01ab76. No account, no API key.
- HALT CLAIM PROVEN: `openadapt flow replay ./openadapt-quickstart/bundle --drift modal` → "Replay HALTED: qs-halt/REPORT.md".
- m
```

**Corrections:** The surveyor's factual claims are all accurate — pivot, three phases, zero model calls, governed repair, halt-with-evidence, macOS+Accessibility, 2026-08-12 activity, PyPI 1.12.1 / >=3.10,<3.13. I could not falsify a single one. What the surveyor omitted is what downgrades this from ADOPT to TRIAL:

1. WRONG FIT FOR THE GOAL — the decisive gap. OpenAdapt is a record-once/replay-deterministically workflow compiler. There is no real-time, streaming, or continuous input surface anywhere in it. It cannot be a gesture-to-cursor substrate. The only sane use is gesture-as-discrete-trigger for an already-compiled bundle, or via `openadapt flow emit-mcp` / `emit-skill` to expose a bundle to an LLM computer-use loop. The surveyor labelled it "orchestration" without noting that the orchestration it does is batch, not live.

2. macOS actuation is WINDOW-SCOPED, not desktop-scoped. `MacOSBackend.__init__` raises ValueError on an empty `app` name, and `_assert_bound_physical_target` raises MacOSBackendError ("Refusing coordinate/global input against a stale window mapping") unless the bound window is still frontmost, focused-main, and the click point resolves to that exact window_id. It is architecturally designed to refuse free-form desktop control. That is the opposite of what a Leap cursor layer needs, and it is not overridable by config.

3. This repo is now a LAUNCHER, not the engine. README: "The compiler and governed runtime are implemented in openadapt-flow. This repository provides the unified `openadapt` CLI and compatibility surface, not a second engine." The engine repo has 3 stars. The 1676 stars belong to the pre-pivot 2023-2025 LLM-replay product and are NOT a signal of adoption for what exists today.

4. BUS FACTOR 1. Commits since 2026-05-01: OpenAdapt = 70 by Richard Abrich, 36 OpenAdapt Bot, 10 dependabot — zero other humans. openadapt-flow = 472 by Richard Abrich, 77 semantic-release, 5 dependabot — zero other humans. Three-plus months, one contributor, across both repos.

5. The clean issue tracker is a RESET, not health. ~10 legacy issues were mass-closed in a single sweep on 2026-01-17 (#951, #948, #941, #937, #935, #925, #924 all closed within seconds of each other) during the pivot. Low open-issue count on a 1676-star repo is explained by that, not by robustness.

6. VIOLENT VERSION CHURN. 89 PyPI releases total; 1.7.0 (2026-07-19) to 1.12.1 (2026-08-11) is six minor versions in 23 days, with openadapt-flow independently at 1.31.0. Any integration must hard-pin both `openadapt==` and `openadapt-flow==`; the surveyor's "1.12.1" will be stale within days.

7. COMMERCIAL GRAVITY understated. The local path genuinely needs no account (I verified), but the run output emits "metering class billable (this local tutorial was not reported or charged)", and `openadapt deploy` steers to app.openadapt.ai Cloud connectors and ingest tokens. The OSS local runtime is real and MIT, but it is the funnel for a hosted governed-execution product; expect the local surface to be shaped by that.

8. Healthcare-oriented defaults leak. Writing a report fired `PlaintextPHIWarning` by default because the `privacy` extra is not installed. Harmless here, but signals the design target is regulated clinical RPA, not desktop HCI.

9. One genuine unmentioned PLUS: requires_python <3.13,>=3.10 means it installs into the exact CPython 3.12 venv the Leap CFFI module already requires. Both can share one interpreter — verified, since I installed it into a 3.12.13 arm64 venv on this machine.

Bottom line: everything the surveyor asserted is true; the candidate is simply not the layer the goal needs. TRIAL as a downstream workflow-execution target reachable from a gesture, or as the MCP surface for the agent loop. REJECT it if it was proposed as the cursor/click actuation substrate.
