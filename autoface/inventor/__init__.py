"""The only package that talks to Inventor.

Everything here uses late-bound COM (``win32com.client.dynamic``): no makepy,
no gen_py cache — the #1 pywin32 failure mode inside PyInstaller one-file
builds — and one exe drives Inventor 2020–2026 because it binds by name at
runtime. Enum values are hard-coded in ``com`` for the same reason.

``scan`` reads the session into plain dataclasses; ``export`` performs the
per-row export; ``probes`` are the read-only checks the user runs against a
real drawing before trusting a batch. Modules import on any platform; only
attaching needs Windows + pywin32.
"""
