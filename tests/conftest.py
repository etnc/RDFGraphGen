import signal

import pytest

TEST_TIME_LIMIT_SECONDS = 120


@pytest.fixture(autouse=True)
def fail_instead_of_hanging():
    """A test that hangs (e.g. generation that never ends) fails after a time limit instead of blocking the run."""
    if not hasattr(signal, "SIGALRM"):  # not available on Windows
        yield
        return

    def on_timeout(signum, frame):
        raise TimeoutError(f"the test did not finish within {TEST_TIME_LIMIT_SECONDS} seconds")

    previous_handler = signal.signal(signal.SIGALRM, on_timeout)
    signal.alarm(TEST_TIME_LIMIT_SECONDS)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous_handler)
