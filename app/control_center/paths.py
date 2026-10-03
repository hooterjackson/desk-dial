"""Per-user paths of the installed app, Desk Dial (rename-desk-dial.md sections 3.4 and 14.2 step 1).

One module builds the home folder and everything under it, so the app, its logs, its data, the
device backups and the credential stores never disagree about where they live::

    %LOCALAPPDATA%\\DeskDial\\                 home()             HOME_NAME
        data\\settings.json, credentials.bin    data_dir()         (the frozen app's Settings data)
        data\\queue-ledger.json                 queue_ledger_file()
        data\\profiles\\user\\, profiles\\updates\\   profiles_user_dir(), profiles_updates_dir()
                                                (app profiles, imported / fetched; a source checkout
                                                keeps them in local\\profiles\\, as ui.DATA_DIR)
        logs\\app.log(.1-.3), crash.log(.1), status.json, smoke-test.json, music-check.json
                                                logs_dir()
        backups\\control-center-inventory-*.json
                                                backups_dir()
        credentials.bin                         credential_store_file() (CredentialStore's default)
        queue-recovery.bin, shuffle-restore.bin next to it (sonos.py derives them with with_name)

The pre-rename home ``%LOCALAPPDATA%\\NanoDControlCenter\\`` (LEGACY_HOME_NAME) belongs to the pinned
rollback bundles (desktop v2-v6), which hard-code it. The app never reads or writes it: the installer
(Install-Desktop.ps1, through its task-context step Install-UserData.ps1) copies the whole old home to
the Desk Dial home once, hash verified, and keeps the old one untouched as the backup (lead ruling on
the rename, item 3). Internal identifiers keep their old names (section 10: the mutex and event
``Local\\NanoDControlCenter.*``, the ``NANOD-CREDENTIALS-1`` header, the ``control_center`` package).

Every function reads LOCALAPPDATA when it is called, so tests can point it elsewhere. Pure: no I/O.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

HOME_NAME = "DeskDial"                     # %LOCALAPPDATA%\DeskDial (and Programs\DeskDial\DeskDial.exe)
LEGACY_HOME_NAME = "NanoDControlCenter"    # the rollback bundles' home; read only by the installer


def local_appdata() -> Path:
    """%LOCALAPPDATA%, or '.' when it is not set (as the credential stores always did)."""
    return Path(os.environ.get("LOCALAPPDATA", "."))


def home() -> Path:
    return local_appdata() / HOME_NAME


def data_dir() -> Path:
    return home() / "data"


def logs_dir() -> Path:
    return home() / "logs"


def backups_dir() -> Path:
    return home() / "backups"


def credential_store_file() -> Path:
    """CredentialStore's default file, in the home root: queue-recovery.bin and shuffle-restore.bin
    live next to it (sonos.py derives them with ``with_name``)."""
    return home() / "credentials.bin"


def queue_ledger_file() -> Path:
    return data_dir() / "queue-ledger.json"


def app_data_dir(frozen=None) -> Path:
    """Settings data as ui.DATA_DIR resolves it: data_dir() in the installed (frozen) app, the source
    checkout's local/ otherwise. `frozen` None = read sys.frozen."""
    if frozen is None:
        frozen = bool(getattr(sys, "frozen", False))
    return data_dir() if frozen else Path(__file__).resolve().parents[1] / "local"


def profiles_dir(frozen=None) -> Path:
    """App profiles the owner added (plan section 5a): data/profiles (local/profiles in a checkout)."""
    return app_data_dir(frozen) / "profiles"


def profiles_user_dir(frozen=None) -> Path:
    """Imported profiles: highest precedence, never overwritten by a fetch."""
    return profiles_dir(frozen) / "user"


def profiles_updates_dir(frozen=None) -> Path:
    """Fetched profiles (profile_updates.py, lane DD-C): above the bundled ones, below user/."""
    return profiles_dir(frozen) / "updates"


def bundled_profiles_dir(frozen=None) -> Path:
    """The app profiles shipped with Desk Dial (plan section 5a, read only): ``sys._MEIPASS/profiles`` in
    the installed (frozen) app (Build-Desktop.ps1 ``--add-data profiles;profiles``), the repo's
    ``profiles/`` in a source checkout. `frozen` None = read sys.frozen."""
    if frozen is None:
        frozen = bool(getattr(sys, "frozen", False))
    if frozen:
        base = getattr(sys, "_MEIPASS", None)
        return Path(base) / "profiles" if base else Path(sys.executable).resolve().parent / "_internal" / "profiles"
    return Path(__file__).resolve().parents[1] / "profiles"
