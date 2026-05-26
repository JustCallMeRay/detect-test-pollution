from __future__ import annotations

import pathlib
import random

import pytest

from detect_test_pollution import GtestFramework
from tests.create_gtest_test import _compile_gtest_prj
from tests.create_gtest_test import _find_test

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

# C++ snippets used across tests (bodies only – wrapped in an anonymous
# namespace with the gtest header by _make_test_file).

_CODE_THREE_TESTS = """\
TEST(SuiteA, TestOne)  {}
TEST(SuiteA, TestTwo)  {}
TEST(SuiteB, TestThree) {}
"""

_CODE_PASS_AND_FAIL = """\
TEST(Suite, AlwaysPass) { ASSERT_TRUE(true); }
TEST(Suite, AlwaysFail) { ASSERT_TRUE(false); }
"""

_CODE_ALL_PASS = """\
TEST(Suite, TestOne) {}
TEST(Suite, TestTwo) {}
"""

# A pollution scenario: Mutates mutates global state; Reads depends on it.
_CODE_POLLUTION = """\
static int k = 1;
TEST(Suite, Other1)  {}
TEST(Suite, Other2)  {}
TEST(Suite, Reads)   { ASSERT_EQ(k, 1); }
TEST(Suite, Mutates) { k = 2; }
"""


@pytest.fixture(scope='session')
def build_gtest_binary(tmp_path_factory):
    """
    Session-scoped factory: compile a snippet once per unique code string and
    return the path (str) to the resulting test executable.
    """
    cache: dict[str, str] = {}

    def _build(code: str) -> str:
        if code not in cache:
            build_dir = tmp_path_factory.mktemp('gtest_build')
            exe_dir = build_dir / 'exes'
            exe_dir.mkdir()
            _compile_gtest_prj(code, build_dir, output_dir=exe_dir)
            binaries = _find_test(exe_dir)
            assert binaries, f'No test binary compiled for:\n{code}'
            cache[code] = str(binaries[0])
        return cache[code]

    return _build


@pytest.fixture
def gtest_framework():
    with GtestFramework() as fw:
        yield fw


# ---------------------------------------------------------------------------
# discover_tests
# ---------------------------------------------------------------------------

def test_discover_tests(build_gtest_binary, gtest_framework):
    binary = build_gtest_binary(_CODE_THREE_TESTS)
    tests = gtest_framework.discover_tests(binary)
    assert tests == [
        'SuiteA.TestOne',
        'SuiteA.TestTwo',
        'SuiteB.TestThree',
    ]


def test_discover_tests_all_pass_binary(build_gtest_binary, gtest_framework):
    binary = build_gtest_binary(_CODE_ALL_PASS)
    tests = gtest_framework.discover_tests(binary)
    assert tests == ['Suite.TestOne', 'Suite.TestTwo']


# ---------------------------------------------------------------------------
# does_test_list_pass
# ---------------------------------------------------------------------------

def test_does_test_list_pass_victim_fails_alone(build_gtest_binary, gtest_framework):
    """A test that always fails should fail even with an empty precursor list."""
    binary = build_gtest_binary(_CODE_PASS_AND_FAIL)
    result = gtest_framework.does_test_list_pass(binary, 'Suite.AlwaysFail', [])
    assert result is False


def test_does_test_list_pass_victim_passes_alone(build_gtest_binary, gtest_framework):
    binary = build_gtest_binary(_CODE_PASS_AND_FAIL)
    result = gtest_framework.does_test_list_pass(binary, 'Suite.AlwaysPass', [])
    assert result is True


def test_does_test_list_pass_victim_passes_with_innocent_precursor(
        build_gtest_binary, gtest_framework,
):
    binary = build_gtest_binary(_CODE_ALL_PASS)
    result = gtest_framework.does_test_list_pass(
        binary, 'Suite.TestTwo', ['Suite.TestOne'],
    )
    assert result is True


def test_does_test_list_pass_pollution_detected(build_gtest_binary, gtest_framework):
    """Reads passes alone but fails when Mutates runs first."""
    binary = build_gtest_binary(_CODE_POLLUTION)
    assert pathlib.Path(binary).exists()
    # Passes alone
    assert gtest_framework.does_test_list_pass(binary, 'Suite.Reads', []) is True
    # Fails when Mutates precedes it
    assert gtest_framework.does_test_list_pass(
        binary, 'Suite.Reads', ['Suite.Mutates'],
    ) is False


# ---------------------------------------------------------------------------
# fast_fail
# ---------------------------------------------------------------------------

def test_fast_fail_no_failures(build_gtest_binary, gtest_framework):
    """fast_fail returns '' when every test passes."""
    binary = build_gtest_binary(_CODE_ALL_PASS)
    testids = ['Suite.TestOne', 'Suite.TestTwo']
    rng = random.Random(42)
    result = gtest_framework.fast_fail(binary, list(testids), rng)
    assert result == ''


def test_fast_fail_finds_failing_test(build_gtest_binary, gtest_framework):
    """fast_fail returns the ID of the failing test."""
    binary = build_gtest_binary(_CODE_PASS_AND_FAIL)
    testids = ['Suite.AlwaysPass', 'Suite.AlwaysFail']
    rng = random.Random(42)
    result = gtest_framework.fast_fail(binary, list(testids), rng)
    assert result == 'Suite.AlwaysFail'


# ---------------------------------------------------------------------------
# create_cmd_to_run  (no binary needed)
# ---------------------------------------------------------------------------

def test_create_cmd_tests(gtest_framework):
    ret = gtest_framework.create_cmd_to_run('Suite.TestOne', 'path/to/binary', None)
    assert ret == (
        'detect-test-pollution --failing-test Suite.TestOne '
        '--tests path/to/binary'
    )


def test_create_cmd_with_testids_filename(gtest_framework):
    ret = gtest_framework.create_cmd_to_run('Suite.TestOne', None, 'ids.txt')
    assert ret == (
        'detect-test-pollution --failing-test Suite.TestOne '
        '--testids-filename ids.txt'
    )


def test_create_cmd_neither_raises(gtest_framework):
    with pytest.raises(AssertionError):
        gtest_framework.create_cmd_to_run('Suite.TestOne', None, None)

