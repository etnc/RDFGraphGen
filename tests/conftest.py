import random

import pytest


@pytest.fixture(autouse=True)
def fixed_random_seed():
    # The generator uses the global `random` module; a fixed seed keeps test runs comparable.
    random.seed(20241108)
