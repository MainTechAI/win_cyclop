import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import faulthandler

import pytest
from PySide6.QtWidgets import QApplication
from cyclop_windows.theme import STYLE

@pytest.fixture(scope="session")
def app():
    instance = QApplication.instance() or QApplication([])
    instance.setStyleSheet(STYLE)
    yield instance


HANG_LOG = open(os.environ.get("CYCLOP_HANG_LOG", os.devnull), "w")


@pytest.fixture(autouse=True)
def hang_guard(request):
    """A hung test dumps every thread's stack and exits instead of stalling CI for 25 minutes."""
    HANG_LOG.write(f"\n[running] {request.node.nodeid}\n")
    HANG_LOG.flush()
    faulthandler.dump_traceback_later(180, exit=True, file=HANG_LOG)
    yield
    faulthandler.cancel_dump_traceback_later()


def pytest_runtest_logreport(report):
    """Mirror failure details into the hang log, which CI posts as an annotation."""
    if report.failed:
        HANG_LOG.write(f"\n[FAILED] {report.nodeid}\n{report.longreprtext[-1800:]}\n")
        HANG_LOG.flush()
