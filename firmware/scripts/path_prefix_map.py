"""PlatformIO pre-script (FW-PUB-003): the image carries no absolute build path.

GCC's -fmacro-prefix-map rewrites __FILE__ (framework asserts, log tags) for the PlatformIO packages dir and the
project dir, so no account or folder name reaches the image. Only .rodata strings change.

The maps are appended here, already expanded, as single CCFLAGS list items, not written as build_flags in
platformio.ini: a build_flags token is expanded by SCons later, and a home path with a space in it
("C:\\Users\\someone Last\\.platformio\\packages") would then split into two compiler arguments. A list item stays one
argument (SCons quotes it on the command line) whatever the path holds. Each root is mapped in both slash forms,
because SCons passes Windows sources with backslashes while __FILE__ may carry forward slashes.
"""


def prefix_map_flags(roots):
    """-fmacro-prefix-map flags for [(path, replacement), ...]: each path in its own, '/' and '\\' forms, without a
    trailing separator, '$' escaped for SCons. Later roots are checked first by GCC, so list the outermost first."""
    flags = []
    for path, replacement in roots:
        path = str(path).rstrip("/\\")
        if not path:
            continue
        for form in (path, path.replace("\\", "/"), path.replace("/", "\\")):
            flag = "-fmacro-prefix-map=" + form.replace("$", "$$") + "=" + replacement
            if flag not in flags:
                flags.append(flag)
    return flags


try:
    Import("env")  # noqa: F821  (SCons injects Import into a PlatformIO extra script)
except NameError:   # imported as a module (the host harness): define only
    env = None

if env is not None:
    env.Append(CCFLAGS=prefix_map_flags([(env.subst("$PROJECT_DIR"), "."),
                                         (env.subst("$PROJECT_PACKAGES_DIR"), "pio-pkgs")]))
