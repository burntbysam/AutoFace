"""COM plumbing that runs anywhere: error decoding and the busy-retry loop."""

import pytest

from autoface.inventor import com


class FakeComError(Exception):
    """Shaped like pywintypes.com_error: hresult + excepinfo."""

    def __init__(self, hresult, description="", scode=None):
        super().__init__(hresult, description)
        self.hresult = hresult
        self.excepinfo = (0, "Inventor", description, "", "", scode)
        self.strerror = description


class TestHresults:
    def test_collects_top_level_and_nested_codes(self):
        exc = FakeComError(
            com.DISP_E_EXCEPTION, "busy", scode=com.RPC_E_CALL_REJECTED
        )
        assert com.hresults_of(exc) == {
            com.DISP_E_EXCEPTION,
            com.RPC_E_CALL_REJECTED,
        }

    def test_plain_exceptions_have_no_codes(self):
        assert com.hresults_of(RuntimeError("x")) == set()


class TestBusyDetection:
    def test_call_rejected_is_busy(self):
        assert com.is_busy_error(FakeComError(com.RPC_E_CALL_REJECTED))

    def test_retry_later_hidden_in_excepinfo_is_busy(self):
        exc = FakeComError(
            com.DISP_E_EXCEPTION, scode=com.RPC_E_SERVERCALL_RETRYLATER
        )
        assert com.is_busy_error(exc)

    def test_other_errors_are_not_busy(self):
        assert not com.is_busy_error(FakeComError(-2147024894))  # file not found
        assert not com.is_busy_error(RuntimeError("x"))


class TestErrorText:
    def test_prefers_the_server_description(self):
        exc = FakeComError(com.DISP_E_EXCEPTION, "Unfold failed: no base face")
        assert com.error_text(exc) == "Unfold failed: no base face"

    def test_falls_back_to_str(self):
        assert com.error_text(RuntimeError("plain")) == "plain"

    def test_never_returns_empty(self):
        assert com.error_text(RuntimeError()) == "RuntimeError"


class TestBusyRetry:
    def test_busy_errors_are_retried_until_success(self):
        attempts = []

        def operation():
            attempts.append(1)
            if len(attempts) < 3:
                raise FakeComError(com.RPC_E_CALL_REJECTED, "busy")
            return "done"

        assert com.with_busy_retry(operation, attempts=5, delay=0) == "done"
        assert len(attempts) == 3

    def test_non_busy_errors_raise_immediately(self):
        attempts = []

        def operation():
            attempts.append(1)
            raise RuntimeError("real failure")

        with pytest.raises(RuntimeError):
            com.with_busy_retry(operation, attempts=5, delay=0)
        assert len(attempts) == 1

    def test_persistent_busy_raises_the_last_error(self):
        def operation():
            raise FakeComError(com.RPC_E_CALL_REJECTED, "still busy")

        with pytest.raises(FakeComError):
            com.with_busy_retry(operation, attempts=3, delay=0)


class TestSilentOperation:
    def test_sets_and_restores(self):
        class App:
            SilentOperation = False

        app = App()
        with com.silent_operation(app):
            assert app.SilentOperation is True
        assert app.SilentOperation is False

    def test_survives_an_app_without_the_property(self):
        class Hostile:
            def __getattr__(self, name):
                raise RuntimeError("no such property")

            def __setattr__(self, name, value):
                raise RuntimeError("read only")

        with com.silent_operation(Hostile()):
            pass  # must not raise
