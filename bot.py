"""
OCI Out of Capacity Fix
Version v3.0.0
Moses (@mosesman831)
GitHub: https://github.com/mosesman831/OCI-OcC-Fix

This is now a thin back-compatibility shim. The implementation lives in the
``occfix`` package (see ``spec.md``). The original invocation still works:

    python3 bot.py                       # run with ./configuration.ini + ./config
    python3 bot.py --config c.ini --oci-config oci_cfg
    python3 bot.py validate              # pre-flight checks only

Prefer the ``oci-occ-fix`` console entry point for the full CLI.
"""

from occfix.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
