#!/usr/bin/env python3
"""set_process_name (build/ntdll-unix/env_ios.c) leaves the app's name alone on iOS; no Wine runs.

setprogname keeps the pointer it is given. On iOS that pointer is into a local of the launch
thread (WineProcessBridge.m's exe_path), so once a session ended the app's progname pointed at
unmapped stack and the next getprogname() crashed the app (Just Cause 3, 2026-10-09: UIKit ->
nwi_state_copy -> strdup -> _platform_strlen).  The production function is compiled against a
recording setprogname and called with a stack buffer, as the launch thread calls it: built for
iOS it must not hand setprogname any pointer into that buffer.
Built without WINE_IOS it must still call setprogname with the exe name, which shows the harness
reaches the call.
"""
from pathlib import Path
import os, subprocess, tempfile

root = Path(__file__).resolve().parents[2]
src = (root / "build/ntdll-unix/env_ios.c").read_text()
a = src.index("static void set_process_name( const char *name )")
func = src[a:src.index("\n}\n", a) + 3]

harness = r"""
#include <stdio.h>
#include <string.h>
#define HAVE_SETPROGNAME 1
static const char *kept; static int calls;
static void setprogname(const char *name) { kept = name; calls++; }
""" + func + r"""
static void launch(void)
{
    char exe_path[512];
    snprintf(exe_path, sizeof(exe_path), "%s", "C:\\Program Files (x86)\\Steam\\steamapps\\common\\Just Cause 3\\JustCause3.exe");
    set_process_name(exe_path);
    if (kept && kept >= exe_path && kept < exe_path + sizeof(exe_path)) { puts("kept-stack"); return; }
    if (calls) printf("called:%s\n", kept);
    else puts("not-called");
}
int main(void) { launch(); return 0; }
"""
cc = os.environ.get("CC", "cc")
with tempfile.TemporaryDirectory() as t:
    c = Path(t) / "progname.c"
    c.write_text(harness)
    out = {}
    for label, defs in (("ios", ["-DWINE_IOS=1"]), ("desktop", [])):
        exe = Path(t) / label
        subprocess.run([cc, "-w", *defs, str(c), "-o", str(exe)], check=True)
        out[label] = subprocess.run([str(exe)], check=True, capture_output=True, text=True).stdout.strip()

assert out["desktop"] in ("kept-stack", "called:JustCause3.exe"), out["desktop"]
print("PASS: without WINE_IOS the harness reaches setprogname (%s)" % out["desktop"])
assert out["ios"] == "not-called", "iOS set_process_name handed setprogname a launch-thread pointer: " + out["ios"]
print("PASS: on iOS set_process_name keeps no pointer into the launch thread's stack")
