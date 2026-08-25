"""COM plumbing: attach to Inventor, error decoding, retry, constants.

Late binding means no ``win32com.client.constants``, so the enum values live
here as plain ints. They are stable across Inventor 2020–2026 (verified in the
type library and Autodesk's own documentation); ``--probe session`` asserts
them against a live session.
"""

from __future__ import annotations

import time
from contextlib import contextmanager

# --- DocumentTypeEnum -------------------------------------------------------
kPartDocumentObject = 12290
kAssemblyDocumentObject = 12291
kDrawingDocumentObject = 12292

# --- Document.SubType GUIDs -------------------------------------------------
SHEET_METAL_SUBTYPE = "{9C464203-9BAE-11D3-8BAD-0060B0CE6BB4}"
PART_SUBTYPE = "{4D29B490-49B2-11D0-93C3-7E0706000000}"

# --- PropertyTypeEnum (parts list columns) ----------------------------------
kFileProperty = 45569  # iProperty-backed column (PART NUMBER, DESCRIPTION, …)
kItemPartsListProperty = 45572  # the ITEM column

# --- Design Tracking Properties (for GetFilePropertyId) ---------------------
DESIGN_TRACKING_PROPERTIES = "{32853F0F-3444-11D1-9E93-0060B03C1CA6}"
PROPERTY_ID_PART_NUMBER = 5
PROPERTY_ID_DESCRIPTION = 29

# --- HRESULTs ---------------------------------------------------------------
MK_E_UNAVAILABLE = -2147221021  # 0x800401E3: no running Inventor to attach to
RPC_E_CALL_REJECTED = -2147418111  # 0x80010001: Inventor is busy
RPC_E_SERVERCALL_RETRYLATER = -2147417846  # 0x8001010A: Inventor says try later
DISP_E_EXCEPTION = -2147352567  # server raised; the real code is in excepinfo

_BUSY = {RPC_E_CALL_REJECTED, RPC_E_SERVERCALL_RETRYLATER}


class InventorUnavailable(RuntimeError):
    """COM itself is unavailable: not Windows, or pywin32 is not installed."""


class InventorNotRunning(RuntimeError):
    """No running Inventor session to attach to."""


def _com_modules():
    try:
        import pythoncom
        import win32com.client
    except ImportError as exc:  # not Windows, or pywin32 missing
        raise InventorUnavailable(
            "the Inventor COM bridge needs Windows with pywin32 installed"
        ) from exc
    return pythoncom, win32com.client


def initialize_thread() -> None:
    """COM setup for the calling thread. Every worker thread calls this first.

    COM objects are apartment-bound: each thread attaches on its own and never
    shares objects with another thread.
    """
    pythoncom, _ = _com_modules()
    pythoncom.CoInitialize()


def uninitialize_thread() -> None:
    try:
        pythoncom, _ = _com_modules()
        pythoncom.CoUninitialize()
    except (InventorUnavailable, Exception):  # noqa: BLE001 - teardown only
        pass


def attach():
    """The running Inventor Application, late-bound.

    Going through ``pythoncom.GetActiveObject`` and wrapping the raw IDispatch
    in ``win32com.client.dynamic.Dispatch`` forces late binding even when a
    stale makepy cache exists on the machine.
    """
    pythoncom, client = _com_modules()
    try:
        unknown = pythoncom.GetActiveObject("Inventor.Application")
    except pythoncom.com_error as exc:
        if MK_E_UNAVAILABLE in hresults_of(exc):
            raise InventorNotRunning(
                "Inventor is not running. Start Inventor and open your drawings, "
                "then try again."
            ) from exc
        raise
    dispatch = unknown.QueryInterface(pythoncom.IID_IDispatch)
    return client.dynamic.Dispatch(dispatch)


def hresults_of(exc: BaseException) -> set[int]:
    """Every HRESULT hiding in a pywin32 com_error.

    The interesting code is sometimes the top-level hresult and sometimes the
    scode buried in excepinfo (DISP_E_EXCEPTION wraps the server's real error).
    """
    codes: set[int] = set()
    hresult = getattr(exc, "hresult", None)
    if isinstance(hresult, int):
        codes.add(hresult)
    excepinfo = getattr(exc, "excepinfo", None)
    if isinstance(excepinfo, (tuple, list)) and len(excepinfo) >= 6:
        scode = excepinfo[5]
        if isinstance(scode, int):
            codes.add(scode)
    return codes


def is_busy_error(exc: BaseException) -> bool:
    """True for the two only-happens-out-of-process 'Inventor is busy' errors."""
    return bool(hresults_of(exc) & _BUSY)


def error_text(exc: BaseException) -> str:
    """A readable message from a com_error (or any exception)."""
    excepinfo = getattr(exc, "excepinfo", None)
    if isinstance(excepinfo, (tuple, list)) and len(excepinfo) >= 3 and excepinfo[2]:
        return str(excepinfo[2]).strip()
    strerror = getattr(exc, "strerror", None)
    if strerror:
        return str(strerror).strip()
    return str(exc).strip() or exc.__class__.__name__


def with_busy_retry(operation, attempts: int = 5, delay: float = 0.6):
    """Run ``operation()``, retrying while Inventor rejects the call as busy.

    pywin32 cannot register a COM IMessageFilter, so a sleep-and-retry loop is
    the practical fix for RPC_E_CALL_REJECTED during someone else's command or
    a long recompute. Anything that is not a busy rejection raises through on
    the first attempt.
    """
    last: BaseException | None = None
    for attempt in range(attempts):
        try:
            return operation()
        except Exception as exc:  # noqa: BLE001 - filtered right below
            if not is_busy_error(exc):
                raise
            last = exc
            if attempt < attempts - 1:
                time.sleep(delay * (attempt + 1))
    raise last  # type: ignore[misc]


@contextmanager
def silent_operation(app):
    """Suppress Inventor's modal prompts for the duration of a batch.

    A modal dialog raised mid-call blocks an external COM call indefinitely;
    SilentOperation auto-accepts most of them. Always restored, and never
    allowed to fail the run — it is a mitigation, not a requirement.
    """
    previous = None
    try:
        previous = bool(app.SilentOperation)
        app.SilentOperation = True
    except Exception:  # noqa: BLE001 - best effort
        pass
    try:
        yield
    finally:
        try:
            app.SilentOperation = bool(previous)
        except Exception:  # noqa: BLE001 - best effort
            pass
