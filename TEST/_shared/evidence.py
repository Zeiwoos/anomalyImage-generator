import time
import unittest

class EvidenceResult(unittest.TextTestResult):
    def __init__(self, *args):
        super().__init__(*args)
        self.records = []
        self.started = {}
    def startTest(self, test):
        self.started[test.id()] = time.monotonic()
        super().startTest(test)
    def record(self, test, status, detail=""):
        self.records.append({"test": test.id(), "purpose": test.shortDescription() or "",
                             "status": status, "seconds": round(time.monotonic() - self.started.get(test.id(), time.monotonic()), 4),
                             "detail": detail})
    def addSuccess(self, test):
        super().addSuccess(test)
        self.record(test, "passed")
    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.record(test, "failed", self._exc_info_to_string(err, test))
    def addError(self, test, err):
        super().addError(test, err)
        self.record(test, "error", self._exc_info_to_string(err, test))
    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.record(test, "skipped", reason)
    def addExpectedFailure(self, test, err):
        super().addExpectedFailure(test, err)
        self.record(test, "expected_failure", self._exc_info_to_string(err, test))
    def addUnexpectedSuccess(self, test):
        super().addUnexpectedSuccess(test)
        self.record(test, "unexpected_success")
    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        if err is not None:
            self.record(subtest, "failed" if issubclass(err[0], test.failureException) else "error", self._exc_info_to_string(err, test))
