#include <Python.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <mach-o/dyld.h>
#include <libgen.h>
#include <sys/stat.h>

#ifdef __APPLE__
#import <Foundation/Foundation.h>
#import <AppKit/AppKit.h>
#endif

int main(int argc, char *argv[]) {
#ifdef __APPLE__
    setprogname("DRPS5");
    @autoreleasepool {
        [[NSProcessInfo processInfo] setProcessName:@"DRPS5"];
    }
#endif
    char exec_path[1024];
    uint32_t size = sizeof(exec_path);
    if (_NSGetExecutablePath(exec_path, &size) != 0) {
        fprintf(stderr, "Error resolving executable path\n");
        return 1;
    }

    char real_exec_path[1024];
    if (realpath(exec_path, real_exec_path) == NULL) {
        strncpy(real_exec_path, exec_path, sizeof(real_exec_path));
    }

    // real_exec_path: .../Contents/MacOS/DRPS5
    char macos_dir[1024];
    strncpy(macos_dir, real_exec_path, sizeof(macos_dir));
    char *dir1 = dirname(macos_dir); // .../Contents/MacOS
    char contents_dir[1024];
    strncpy(contents_dir, dir1, sizeof(contents_dir));
    char *dir2 = dirname(contents_dir); // .../Contents

    char resources_dir[1024];
    snprintf(resources_dir, sizeof(resources_dir), "%s/Resources", dir2);

    char target_script[1024];
    snprintf(target_script, sizeof(target_script), "%s/drps5.py", resources_dir);
    if (access(target_script, F_OK) != 0) {
        snprintf(target_script, sizeof(target_script), "/Users/rleon/Documents/PXPLAY/DRPS5/drps5.py");
    }

    // Setup logging directory in ~/.drps5
    const char *home = getenv("HOME");
    if (home) {
        char log_dir[1024];
        snprintf(log_dir, sizeof(log_dir), "%s/.drps5", home);
        mkdir(log_dir, 0755);
        char log_file[1024];
        snprintf(log_file, sizeof(log_file), "%s/launcher.log", log_dir);
        FILE *flog = freopen(log_file, "a", stdout);
        if (flog) {
            dup2(fileno(stdout), fileno(stderr));
        }
    }

    // Set PYTHONPATH and environment
    char pypath[4096];
    snprintf(pypath, sizeof(pypath),
        "%s:%s/pyremoteplay:%s/.venv/lib/python3.9/site-packages:/Users/rleon/Documents/PXPLAY/DRPS5:/Users/rleon/Documents/PXPLAY/DRPS5/pyremoteplay:/Users/rleon/Documents/PXPLAY/DRPS5/.venv/lib/python3.9/site-packages",
        resources_dir, resources_dir, resources_dir);
    setenv("PYTHONPATH", pypath, 1);
    setenv("PYTHONUNBUFFERED", "1", 1);
    setenv("TK_SILENCE_DEPRECATION", "1", 1);

    // Change directory to Resources
    chdir(resources_dir);

    // Build arguments: filter macOS -psn_... args and redundant drps5.py invocations
    char **py_argv = (char **)malloc((argc + 3) * sizeof(char *));
    py_argv[0] = real_exec_path;
    py_argv[1] = target_script;
    int arg_idx = 2;

    for (int i = 1; i < argc; i++) {
        if (strncmp(argv[i], "-psn", 4) != 0) {
            if (strcmp(argv[i], target_script) == 0 || strstr(argv[i], "drps5.py") != NULL) {
                continue;
            }
            py_argv[arg_idx++] = argv[i];
        }
    }
    py_argv[arg_idx] = NULL;

    Py_SetProgramName(L"DRPS5");
#ifdef __APPLE__
    @autoreleasepool {
        [[NSProcessInfo processInfo] setProcessName:@"DRPS5"];
        char icns_cand[1024];
        snprintf(icns_cand, sizeof(icns_cand), "%s/AppIcon.icns", resources_dir);
        if (access(icns_cand, F_OK) != 0) {
            snprintf(icns_cand, sizeof(icns_cand), "/Applications/DRPS5.app/Contents/Resources/AppIcon.icns");
        }
        if (access(icns_cand, F_OK) == 0) {
            NSString *imgPath = [NSString stringWithUTF8String:icns_cand];
            NSImage *appIcon = [[NSImage alloc] initWithContentsOfFile:imgPath];
            if (appIcon) {
                [[NSApplication sharedApplication] setApplicationIconImage:appIcon];
                [[[NSApplication sharedApplication] dockTile] display];
            }
        }
    }
#endif
    return Py_BytesMain(arg_idx, py_argv);
}
