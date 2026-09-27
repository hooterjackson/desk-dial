"""Build one binary of the current release's firmware (PlatformIO `run`, never upload) and accept or reject it.

The release is nanod_cc5_tooling.CURRENT (1.0.0-cc5.4). It stages the PRESENTATION_V5 12.6 build
ladder (lead ruling R-m), one binary per run (--binary, default D). The binaries this script builds are the
active ones (tooling.ACTIVE_BINARIES):
  D  release candidate (A + fixes): PLATFORMIO_BUILD_FLAGS "-DCC_BUILD_BINARY=4" on the source defaults
     (CC_LCD_DMA 1, CC_LCD_PERIOD_MS 16, CC_ART_ASYNC 1);
  E  fallback (C + fixes): PLATFORMIO_BUILD_FLAGS "-DCC_LCD_DMA=0 -DCC_LCD_PERIOD_MS=33 -DCC_ART_ASYNC=0
     -DCC_BUILD_BINARY=5" (no DMA, R5 off, 33 ms).
The first ladder, A (the source defaults, built into the project's own .pio/build/nanofoc_d), B
("-DCC_LCD_PERIOD_MS=33 -DCC_ART_ASYNC=0") and C ("-DCC_LCD_DMA=0 -DCC_LCD_PERIOD_MS=33 -DCC_ART_ASYNC=0"), is
retired (tooling.RETIRED_BINARIES: A was rolled back on 2026-09-26 with a dark LCD, B carries the same DMA
defect, C is superseded by E): --binary A|B|C is refused by argparse (exit 2) and nothing is built or written.
Every binary but A builds into its own PLATFORMIO_BUILD_DIR (.pio/build-cc5.4-D, .pio/build-cc5.4-E), so no
binary ever overwrites another; PlatformIO appends PLATFORMIO_BUILD_FLAGS to platformio.ini's build_flags. Any
PLATFORMIO_BUILD_FLAGS, PLATFORMIO_SRC_BUILD_FLAGS, PLATFORMIO_BUILD_UNFLAGS or PLATFORMIO_BUILD_DIR in
the caller's environment is dropped first. .pio/libdeps is only read.

A binary is accepted only when all hold:
  * the PlatformIO log contains [SUCCESS];
  * its firmware.bin is an ESP image smaller than app0 (0x140000) containing the release's version;
  * the compiled pipeline is the binary's (tooling.binary_image_problems / binary_elf_problems): the image
    holds the R5 decode task name "ArtDecode" exactly in A and D, and firmware.elf links the R3 draw buffer
    draw_buf2 exactly in A, B and D (the 33 ms period is not visible in the image: diag lcdPeriodMs reports
    it on the device); a numbered binary (D, E) holds exactly its build marker "cc-build-binary:<n>"
    (CC_BUILD_BINARY; recorded as pipelineEvidence.buildMarkers and diagBuild, the letter diag "build"
    reports); and the image differs from the other binaries' accepted images;
  * the LCD data-line gate (tooling.lcd_mosi_gate, recorded as "lcdMosiGate": the pins, port, dma,
    reattachRequired, reattachLinked, passed): platformio.ini's TFT pins with the binary's flags and TFT_eSPI's S3
    rule (an unset or -1 TFT_MISO becomes TFT_MOSI) give the effective pins; a binary that compiles DMA in
    (tft.initDMA()) with MISO == MOSI must link cc_lcd_mosi_reattach (without it the build is binary A's dark LCD)
    and call it right after every tft.initDMA() and before startWrite (tooling.lcd_run_call_order: a read-only
    objdump of LcdThread::run() in firmware.elf, recorded as callOrder; an order that cannot be read fails the gate),
    and USE_HSPI_PORT is refused (the encoder owns HSPI);
  * presentation 5 releases: the PRESENTATION_V5 12.4 build-only heap projection (tooling.heap_projection
    of the RAM the linker reports, H = the 512 B SPI DMA descriptors in the DMA binaries A, B and D, 0 in C and
    E) is at least 45,056 B, and firmware.elf's symbol table gives sizeof(CCFrame) and the size of the ALIVE
    instance (tooling.v5_size_record: st_size of hmi_thread.cpp's cc_hmi_frame and alive). It is recorded as
    "heapProjection" (ramUsedBytes, the delta against cc5.3, the JSON document and DMA terms,
    heapMinFreeProjected, required, passed, ccFrameBytes, aliveInstanceBytes and the symbols read).
The complete log is written as UTF-8 to work/nanod-<tag>-build.log (nanod-cc5.4-D-build.log,
nanod-cc5.4-E-build.log; A, B, C and earlier releases keep their own logs). An existing log of the same name is
evidence (a packaged manifest pins its SHA-256 in its gates), so it is renamed first to
nanod-<tag>-build.superseded-<UTC>.log, never overwritten. Size, SHA-256, headroom, the log's SHA-256
(logSha256) and the binary's flags and pipeline are recorded in app/diagnostics/
<prefix>-build.json (cc5.4-D-build.json, cc5.4-E-build.json; an older record of the same binary is kept as
*.superseded-*; the records of earlier releases and of the other binaries are never touched). No device, git or
network access (PlatformIO packages are already installed).
"""
import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import struct
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nanod_cc5_tooling as t  # noqa: E402  (no side effects on import)

# Build-shaping variables PlatformIO reads from the environment: never inherited from the caller.
PIO_BUILD_VARIABLES = ("PLATFORMIO_BUILD_FLAGS", "PLATFORMIO_SRC_BUILD_FLAGS", "PLATFORMIO_BUILD_UNFLAGS",
                       "PLATFORMIO_BUILD_DIR")


def heap_projection_problems(report, p, symbols=None):
    """PRESENTATION_V5 12.4 for a presentation 5 release: record ``heapProjection`` in ``report`` from
    its ``ramUsedBytes`` and, from firmware.elf's symbol table (`symbols`, tooling.elf_symbols; None when
    there is no readable ELF), sizeof(CCFrame) and the ALIVE instance size; return the problems (none for
    an earlier release, which records nothing). H (the SPI DMA descriptors) counts only for a binary that
    compiles DMA in (A, B and D, not C and E)."""
    if getattr(p, "presentation", 4) < 5:
        return []
    ram_used = report.get("ramUsedBytes")
    if not isinstance(ram_used, int):
        report["heapProjection"] = None
        return ["the RAM line is missing, so the heap projection (PRESENTATION_V5 12.4) cannot be made"]
    pipeline = getattr(p, "pipeline", None)
    projection = t.heap_projection(ram_used, dma=pipeline["lcdDma"] if pipeline else True)
    projection.update(t.v5_size_record(symbols))
    report["heapProjection"] = projection
    problems = []
    if not projection["passed"]:
        problems.append(f"heapMinFreeProjected {projection['heapMinFreeProjected']} B < {projection['required']} B "
                        "(PRESENTATION_V5 12.4)")
    missing = [what for what, key in (("sizeof(CCFrame)", "ccFrameBytes"), ("the ALIVE instance size", "aliveInstanceBytes"))
               if not isinstance(projection.get(key), int)]
    if missing:
        where = "firmware.elf is missing or unreadable" if symbols is None else (
            "no data object named " + " / ".join(t.CCFRAME_SYMBOLS + t.ALIVE_INSTANCE_SYMBOLS)
            + " with one size in firmware.elf's symbol table")
        problems.append(f"{' and '.join(missing)} not recorded ({where}); PRESENTATION_V5 12.4 records both "
                        "for every binary")
    return problems


def read_symbols(elf_path):
    """(firmware.elf's symbol table as tooling.elf_symbols, or None; the problem when it exists but cannot be
    read, else None)."""
    if not elf_path.is_file():
        return None, None
    try:
        return t.elf_symbols(elf_path), None
    except (OSError, ValueError, IndexError, struct.error) as exc:
        return None, f"firmware.elf could not be read ({type(exc).__name__})"


def build_environment(p):
    """The environment PlatformIO runs with for binary `p`: the pinned core, UTF-8, and for every binary but A its
    flags and build folder; the caller's build-shaping variables never leak in."""
    env = {k: v for k, v in os.environ.items() if k.upper() not in PIO_BUILD_VARIABLES}
    env.update(PLATFORMIO_CORE_DIR=str(t.PIO_CORE), PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    if p.build_flags:
        env["PLATFORMIO_BUILD_FLAGS"] = " ".join(p.build_flags)
    if p.build_dir is not None:
        env["PLATFORMIO_BUILD_DIR"] = str(p.build_dir)
    return env


def read_call_order(elf_path):
    """(the LCD setup calls LcdThread::run() makes, in order, from firmware.elf (tooling.lcd_run_call_order: a
    read-only objdump of that one function), or None; why it could not be read, else None)."""
    if not elf_path.is_file():
        return None, "firmware.elf is missing"
    try:
        return t.lcd_run_call_order(elf_path), None
    except t.CALL_ORDER_ERRORS as exc:
        return None, f"{type(exc).__name__}: {exc}"


def mosi_gate(p, names, call_order=None, call_order_error=None):
    """The LCD data-line gate of ladder binary `p` (tooling.lcd_mosi_gate) from platformio.ini and its flags, with
    firmware.elf's symbol names `names` (None: no readable ELF) and LcdThread::run()'s call order (read_call_order).
    The record notes where the pins came from."""
    ini = t.FIRMWARE_SOURCE / "platformio.ini"
    try:
        text = ini.read_text(encoding="utf-8")
    except OSError as exc:
        text = ""
        config = t.tft_spi_config(text, p.build_flags)
        config["problems"] = [f"platformio.ini could not be read ({type(exc).__name__}), so the LCD data line cannot "
                              "be checked"]
    else:
        config = t.tft_spi_config(text, p.build_flags)
    gate = t.lcd_mosi_gate(config, names, p.binary, call_order, call_order_error)
    gate["source"] = f"{ini.name} [env:{t.PIO_ENV}] build_flags + PLATFORMIO_BUILD_FLAGS; {config['rule']}"
    return gate


def sibling_problems(p, sha256):
    """The image must differ from every other binary's accepted image (identical bytes would mean the
    flags did not take effect)."""
    problems = []
    for other in p.variants():
        if other is p or not other.build_report.is_file():
            continue
        try:
            record = t.load_json(other.build_report)
        except (OSError, ValueError):
            continue
        if record.get("accepted") and record.get("sha256") == sha256:
            problems.append(f"the image is identical to binary {other.binary}'s accepted image "
                            f"({other.build_report.name}): the build flags did not take effect")
    return problems


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    choices = t.binary_choices()
    if choices:
        parser.add_argument("--binary", choices=choices, default=choices[0],
                            help=f"the PRESENTATION_V5 12.6 binary to build (default {choices[0]})")
    args = parser.parse_args(argv)
    t.console_utf8()
    p = t.CURRENT.binary_profile(getattr(args, "binary", None))
    python = t.PIO_VENV / "Scripts" / "python.exe"
    command = [str(python), "-m", "platformio", "run", "-d", str(t.FIRMWARE_SOURCE), "-e", t.PIO_ENV]
    assert "upload" not in command and "-t" not in command, "Build only"
    env = build_environment(p)
    image_path, elf_path = p.built_image, p.built_elf
    started = datetime.now(timezone.utc)
    # The previous log of this binary is evidence (a packaged manifest pins its SHA-256): keep it, never overwrite.
    previous_log = t.archive_existing(p.build_log)
    with p.build_log.open("x", encoding="utf-8") as output:
        output.write(f"$ {' '.join(command)}\nPLATFORMIO_CORE_DIR={t.PIO_CORE}\n")
        if p.binary:
            output.write(f"binary {p.binary} ({t.BINARY_ROLES[p.binary]}); PLATFORMIO_BUILD_FLAGS="
                         f"{env.get('PLATFORMIO_BUILD_FLAGS', '')}; PLATFORMIO_BUILD_DIR="
                         f"{env.get('PLATFORMIO_BUILD_DIR', '(project default)')}\n")
        output.write(f"started {started.isoformat()}\n\n")
        output.flush()
        result = subprocess.run(command, env=env, stdout=output, stderr=subprocess.STDOUT,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    log_bytes = p.build_log.read_bytes()
    log = log_bytes.decode("utf-8", errors="replace")
    print("\n".join(log.splitlines()[-30:]))
    report = {"version": p.version, "startedUtc": started.isoformat(), "command": command,
              "platformioCoreDir": str(t.PIO_CORE), "log": str(p.build_log),
              "logSha256": t.sha256_bytes(log_bytes), "logBytes": len(log_bytes),
              "previousLogKeptAs": previous_log.name if previous_log else None, "exitCode": result.returncode,
              "success": "[SUCCESS]" in log, "image": str(image_path), "slotBytes": t.APP_SIZE,
              "cc4Bytes": t.CC4_IMAGE_BYTES, "fromVersion": p.from_version, "fromBytes": p.from_image_bytes,
              "problems": []}
    if p.binary:
        report.update(binary=p.binary, role=t.BINARY_ROLES[p.binary], buildFlags=list(p.build_flags),
                      buildDir=str(p.build_dir) if p.build_dir is not None else None, pipeline=p.pipeline,
                      buildNumber=p.build_number, diagBuild=p.binary if p.build_number is not None else None)
    ram = re.search(r"RAM:.*used (\d+) bytes", log)
    flash = re.search(r"Flash:.*used (\d+) bytes", log)
    report.update(ramUsedBytes=int(ram.group(1)) if ram else None,
                  flashUsedBytes=int(flash.group(1)) if flash else None)
    if result.returncode or not report["success"]:
        report["problems"].append("PlatformIO did not report [SUCCESS]")
    symbols, elf_problem = read_symbols(elf_path)
    if elf_problem and (p.binary or getattr(p, "presentation", 4) >= 5):
        report["problems"].append(elf_problem)
    report["problems"] += heap_projection_problems(report, p, symbols)
    if p.binary:
        # The LCD data line (binary A's dark LCD): checked on every ladder build, before the image is looked at.
        call_order, call_order_error = read_call_order(elf_path) if symbols is not None else (None, elf_problem)
        report["lcdMosiGate"] = mosi_gate(p, None if symbols is None else {name for name, _, _ in symbols},
                                          call_order, call_order_error)
        report["problems"] += report["lcdMosiGate"]["problems"]
    if image_path.is_file():
        image = image_path.read_bytes()
        report.update(bytes=len(image), sha256=t.sha256_bytes(image),
                      headroomBytes=t.APP_SIZE - len(image), deltaFromCc4Bytes=len(image) - t.CC4_IMAGE_BYTES,
                      deltaFromPreviousBytes=len(image) - p.from_image_bytes,
                      imageModifiedUtc=datetime.fromtimestamp(image_path.stat().st_mtime, timezone.utc).isoformat(),
                      containsVersion=p.version.encode("ascii") in image)
        report["problems"] += t.app_image_problems(image, p.version)
        if p.binary:
            names = None if symbols is None else {name for name, _, _ in symbols}
            report["pipelineEvidence"] = {
                "imageHoldsR5Task": t.R5_IMAGE_MARKER in image,
                "elfLinksR3Buffer": None if names is None else t.R3_ELF_SYMBOL in names,
                "periodMs": "not visible in the image; diag lcdPeriodMs reports it on the device",
                "buildMarkers": t.build_markers(image),
                "buildMarkerExpected": (f"{t.BUILD_MARKER_PREFIX.decode('ascii')}{p.build_number}"
                                        if p.build_number is not None else None),
                "elfLinksMosiReattach": None if names is None else t.mosi_reattach_linked(names)}
            report["problems"] += t.binary_image_problems(image, p.binary)
            report["problems"] += t.binary_elf_problems(names, p.binary)
            report["problems"] += sibling_problems(p, report["sha256"])
    else:
        report["problems"].append("firmware.bin was not produced")
    report["accepted"] = not report["problems"]
    archived = t.write_json_evidence(p.build_report, report)
    which = f" binary {p.binary} ({t.BINARY_ROLES[p.binary]})" if p.binary else ""
    print(f"\nBuild{which} {'ACCEPTED' if report['accepted'] else 'REJECTED'}: "
          f"{report.get('bytes')} B ({p.from_version} {p.from_image_bytes} B), sha256 {report.get('sha256')}")
    if report.get("heapProjection"):
        projection = report["heapProjection"]
        print(f"Heap projection: {projection['heapMinFreeProjected']} B (required {projection['required']} B; "
              f"RAM used {projection['ramUsedBytes']} B, {projection['ramDeltaVsCc53']:+d} B vs cc5.3, "
              f"H {projection['hBytes']} B); sizeof(CCFrame) {projection.get('ccFrameBytes')} B, "
              f"ALIVE instance {projection.get('aliveInstanceBytes')} B")
    if report.get("lcdMosiGate"):
        gate = report["lcdMosiGate"]
        order = gate.get("callOrder")
        print(f"LCD data line: MOSI GPIO{gate['pins']['mosi']}, effective MISO {gate['pins']['effectiveMiso']} "
              f"({gate['port']}), DMA {gate['dma']}; re-attach required {gate['reattachRequired']}, linked "
              f"{gate['reattachLinked']}; LcdThread::run() calls "
              f"{', '.join(order) if order is not None else '(not read)'}: {'passed' if gate['passed'] else 'FAILED'}")
    print(f"Record: {p.build_report}" + (f" (previous kept as {archived.name})" if archived else ""))
    print(f"Log: {p.build_log} sha256 {report['logSha256']}"
          + (f" (previous kept as {previous_log.name})" if previous_log else ""))
    for problem in report["problems"]:
        print(" -", problem)
    return 0 if report["accepted"] else 1


if __name__ == "__main__":
    sys.exit(main())
