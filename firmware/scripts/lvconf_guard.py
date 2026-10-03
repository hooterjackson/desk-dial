"""PlatformIO pre-script (FW-BUG-017): rebuild every object when include/lv_conf.h changes.

lv_conf.h reaches LVGL through a macro include (-DLV_CONF_PATH=...), which the build's dependency scan cannot see.
After an edit to it (LV_OBJ_STYLE_CACHE, LV_MEM_SIZE, ...) a plain incremental `pio run` recompiled only some units,
and the image mixed two lv_obj_t layouts. This script adds -DCC_LV_CONF_SHA=<first 64 bits of the file's SHA-256>
to every compile command (src, libraries and framework alike): any change to lv_conf.h changes every command line,
so SCons recompiles every object. No source reads the define; the image is otherwise unchanged.
"""
import hashlib
import os


def lv_conf_define(project_dir):
    """("CC_LV_CONF_SHA", "0x<16 hex digits>") for <project_dir>/include/lv_conf.h; line endings do not count."""
    path = os.path.join(project_dir, "include", "lv_conf.h")
    with open(path, "rb") as handle:
        data = handle.read().replace(b"\r\n", b"\n")
    return ("CC_LV_CONF_SHA", "0x" + hashlib.sha256(data).hexdigest()[:16])


try:
    Import("env")  # noqa: F821  (SCons injects Import into a PlatformIO extra script)
except NameError:   # imported as a module (the host harness): define only
    env = None

if env is not None:
    env.Append(CPPDEFINES=[lv_conf_define(env.subst("$PROJECT_DIR"))])
