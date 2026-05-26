
from collections.abc import Iterable
from functools import lru_cache
import glob
import os
import pathlib
import subprocess
import tempfile
import sys
from typing import AsyncGenerator, Any

async def _find_possible_compilers() -> AsyncGenerator[pathlib.Path, Any]:
    """
    Runs whereis or where on various common C++ compilers and yields all the paths available
    """
    compilers = ['g++', 'clang++', 'c++', 'clang', 'gcc']
    find_command = 'where' if os.name == 'nt' else 'which'

    for compiler in compilers:
        try:
            result = subprocess.run(
                [find_command, compiler],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                yield pathlib.Path(result.stdout.strip())
        except (subprocess.TimeoutExpired, FileNotFoundError):
            continue
    # Then go through CXX environment variable (cmake looks here)

    # Then go through POL_CXX env var (ours)

    raise RuntimeError(f"No compilers found. Please install g++, clang++ or c++ and ensure {find_command} prints as expected.")

async def _is_valid_compiler(path: pathlib.Path) -> bool:
    """
    Checks if the compiler works
    """
    try:
        # TODO: Something better than version
        result = subprocess.run(
            (str(path), '--version'),
            capture_output=True,
            text=True,
            timeout=5
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False

async def _get_valid_compiler() -> pathlib.Path:
    """
    Runs _find_possible_compilers and _is_valid_compiler to find the first valid compiler
    """
    # compilers = await 
    
    async for compiler in _find_possible_compilers():
        if await _is_valid_compiler(compiler):
            return compiler
    
    raise RuntimeError("No valid C++ compiler found")

VALID_COMPILER: pathlib.Path | None = None

async def _compile_cpp(
        code :str,
        output_path: pathlib.Path,
        compiler_args: Iterable[str]|None = None,
    ) -> pathlib.Path:
    """
    Compiles the given C++ code and returns the path to the compiled binary
    """
    global VALID_COMPILER
    if VALID_COMPILER is None:
        VALID_COMPILER = await _get_valid_compiler()
    compiler = VALID_COMPILER
    binary_file = pathlib.Path(output_path).absolute()
    compiler_args = compiler_args or tuple()
    if "-o" not in compiler_args and "-c" not in compiler_args:
        compiler_args = (*compiler_args, '-o', str(binary_file))
    with tempfile.TemporaryDirectory() as temp_dir:
        os.chdir(temp_dir)
        source_file = pathlib.Path("temp_test.cpp")
    
        with open(source_file, 'w') as f:
            f.write(code)
        
        try:
            result = subprocess.run(
                (str(compiler), str(source_file), *compiler_args),
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode != 0:
                raise RuntimeError(f"Compilation failed: {result.stderr}")
            return binary_file
        finally:
            if source_file.exists():
                source_file.unlink()

USER_HAS_CMAKE :bool | None = None
TEST_TARGET = "DTP_TEST"

def _cmake_build(folder: pathlib.Path, output: pathlib.Path) -> None: # (or built binaries?) list[pathlib.Path]:
    """
    builds CMakeLists.txt file from arg: folder, and places executables (only) into arg: output
    """
    cml = folder/"CMakeLists.txt"
    if not cml.exists():
        raise RuntimeError(f"No cmake file")
    global USER_HAS_CMAKE
    if USER_HAS_CMAKE is None:
        cmake_version = subprocess.run(("cmake", "--version"))
        USER_HAS_CMAKE = cmake_version.returncode == 0
    if not USER_HAS_CMAKE:
        raise RuntimeError("Cannot do cmake build")
    cmake_args = os.environ.get("CMAKE_ARGS", "")
    build_ = "C:/WD/me/cache"
    with tempfile.TemporaryDirectory() as build:
        build += "/build"
        cmake_config = subprocess.run((
            "cmake", "-B", build_, "-S", folder.absolute(), "--fresh", f"-D EXECUTABLE_OUTPUT_PATH={output}",
            # makes globing easier later
            "-D CMAKE_EXECUTABLE_SUFFIX=.exe",
            *cmake_args.split(",")
            ),
            # Work security is weird and breaks Ninja's create process
            shell=True,
            
            )
        if cmake_config.returncode != 0:
            raise RuntimeError(f"Failed configure:\n{cmake_config.stderr}")
        cmake_build = subprocess.run(("cmake", "--build", build_, "--target", TEST_TARGET))
        if cmake_build.returncode != 0:
            raise RuntimeError(f"Failed build:\n{cmake_build.stderr}")
    return None

def _get_cache_dir() -> pathlib.Path:
    return pathlib.Path(pathlib.Path(sys.argv[0]).resolve().stem + "cache")

def _make_cmake_project(folder:pathlib.Path, /, gtest_path:pathlib.Path | None = None, gtest_repo: str | None = None):
    """
    folder must contain a test.cpp before calling
    """
    cml_path = folder/"CMakeLists.txt"
    main_path = folder/"test.cpp"
    if not main_path.exists():
        raise RuntimeError("Cowardly refusing to build 0 files")
    fallback_path = _get_cache_dir()/"gtest"
    # get gtest, preferably once
    gtest_path = pathlib.Path("some-non-existing-dir") if gtest_path is None else gtest_path
    gtest_repo = "https://github.com/google/googletest.git" if gtest_repo is None else gtest_repo
    fallback_path = fallback_path.as_posix()
    gtest_path = gtest_path.as_posix()
    cml_getting = (
fr"""
set(_FALLBACK_GTEST_DIR {fallback_path})

include(FetchContent)
if (EXISTS {gtest_path})
   message(STATUS "Using local googletest")
   FetchContent_Declare(
      googletest
      SOURCE_DIR {gtest_path}
   )
   FetchContent_MakeAvailable(googletest)
elseif(EXISTS ${{_FALLBACK_GTEST_DIR}})
   message(STATUS "Using previously pulled googletest")
   FetchContent_Declare(
      googletest
      BINARY_DIR ${{_FALLBACK_GTEST_DIR}}-build
      SOURCE_DIR ${{_FALLBACK_GTEST_DIR}}-src
   )
   FetchContent_MakeAvailable(googletest)
else()
   message(STATUS "Fetching googletest")
   FetchContent_Declare(
      googletest
      GIT_REPOSITORY {gtest_repo}
      GIT_TAG main
      BINARY_DIR ${{_FALLBACK_GTEST_DIR}}-build
      SOURCE_DIR ${{_FALLBACK_GTEST_DIR}}-src
   )
   FetchContent_MakeAvailable(googletest)
endif()
"""
    )
    preamble = "cmake_minimum_required(VERSION 3.25)\nproject(Test_pollution LANGUAGES CXX)\nset(CMAKE_CXX_STANDARD 17)\n"
    # Not adding warnings results in slightly reduced compile times
    cml_exe = f"add_executable({TEST_TARGET} test.cpp)\ntarget_link_libraries({TEST_TARGET} PRIVATE GTest::gtest_main)\n"
    # Work issues: TODO add -static to link flags in env vars
    cml_exe += f"if (WIN32)\ntarget_link_options({TEST_TARGET} PRIVATE -static)\nendif()\n"
    with open(cml_path, "x") as cml:
        cml.write(preamble)
        cml.write(cml_getting)
        cml.write(cml_exe)

def _make_test_file(code:str, folder:pathlib.Path):
    with open(folder/"test.cpp", "x") as test:
        test.write("#include <gtest/gtest.h>\nnamespace {")
        test.write(code)
        test.write("}")

def _make_gtest_prj(code:str, folder:pathlib.Path, /, gtest_path:pathlib.Path | None = None, gtest_repo: str| None = None):
    _make_test_file(code, folder)
    _make_cmake_project(folder, gtest_path=gtest_path, gtest_repo=gtest_repo)

def _compile_gtest_prj(code:str, folder:pathlib.Path, /, output_dir:pathlib.Path|None=None, gtest_path:pathlib.Path |None = None, gtest_repo: str| None = None):
    output_dir = output_dir if output_dir is not None else folder/"build"
    _make_gtest_prj(code, folder, gtest_path=gtest_path, gtest_repo=gtest_repo)
    _cmake_build(folder, output=output_dir)

def _find_test(folder:pathlib.Path) -> list[str]:
    if not folder.exists():
        raise RuntimeError("could not find tests, no tests exists")
    test = (t for t in folder.glob("*.exe") if "DTP_TEST" in t.name)
    return list(test)

def _tests_pass(folder:pathlib.Path) -> bool:
    """
    Runs the test binary and returns true if it passes
    """
    tests = _find_test(folder)
    if not tests:
        raise RuntimeError("No test binary found")
    for test in tests:
        result = subprocess.run((str(test), ))
        if result.returncode != 0:
            return False
    return True

if __name__ == "__main__":
    # _get_github_release()
    with tempfile.TemporaryDirectory() as tmp:
        out_folder = pathlib.Path(tmp)
        exe_folder = out_folder/"exes"

        _compile_gtest_prj("TEST(A,B) {}", out_folder, exe_folder)
        if _tests_pass(exe_folder):
            print("compiled!")


    def _gcc():
        import asyncio
        
        # with tempfile.TemporaryDirectory() as temp_dir:
        temp_dir = pathlib.Path("./build/cpp")
        temp_dir.mkdir(parents=True, exist_ok=True)
        output_path = temp_dir / "test_binary"
        
        exe = asyncio.run(_compile_cpp("int main() { return 0; }", output_path))
        print(f"Compiled binary: {exe}")
        exe_out = subprocess.run((str(exe), ))
        exe_out.check_returncode()
