"""Thin alias kept for old notes: the runner is render_all.py.

  python render_all.py --firmware <fw> --harness <lcd-preview> --app <app> --build <build> --work <scratch>
                       --out <repo>/docs/media [--scenes ...] [--skip-build] [--check] [--no-logo]

This file forwards its arguments unchanged. See README.md in this folder.
"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from render_all import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
