// The .app wrapper's main executable: a Mach-O stub that redirects output to
// ~/.leapinput/menubar.log and execs the venv's `leapinput-menubar`.
//
// Why a compiled stub and not a shell script: macOS attributes TCC decisions
// (Camera, Accessibility) to the *app bundle* that is responsible for a
// process tree, and that attribution needs a real Mach-O main executable with
// a code signature. The menu bar's session is a grandchild of this stub, so
// the camera prompt the session triggers is asked — and remembered — as
// "Leap Menubar". That is also why Contents/Info.plist must carry
// NSCameraUsageDescription: without it macOS refuses the request outright
// instead of prompting, and the session opens a camera that never delivers a
// frame. See scripts/install-menubar-app.sh, which builds both.
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

#define TARGET "@BIN@"

int main(void) {
    const char *home = getenv("HOME");
    if (home) {
        char log[1024];
        snprintf(log, sizeof log, "%s/.leapinput/menubar.log", home);
        freopen(log, "a", stdout);
        freopen(log, "a", stderr);
    }
    execl(TARGET, "leapinput-menubar", (char *)NULL);
    return 1;                   // only reached if the exec failed
}
