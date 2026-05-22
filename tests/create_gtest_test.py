
from collections.abc import Iterable
import os
import pathlib
import subprocess
import tempfile
from typing import AsyncGenerator, Any

async def _find_posible_compilers() -> AsyncGenerator[pathlib.Path, Any]:
    """
    Runs whereis or where on various common C++ compilers and yeilds all the paths availibe
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
    Runs _find_posible_compilers and _is_valid_compiler to find the first valid compiler
    """
    # compilers = await 
    
    async for compiler in _find_posible_compilers():
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

async def _cmake_build(folder: pathlib.Path) -> list[pathlib.Path]:
    cml = folder/"CMakeLists.txt"
    if not cml.exists():
        raise RuntimeError(f"No cmake file")
    if USER_HAS_CMAKE is None:
        cmake_version = subprocess.run(("cmake", "--version"))
        USER_HAS_CMAKE = result.returncode == 0
        

async def _clone_repo(folder: pathlib.Path, repo_url: str ) -> bool

async def _get_github_release(asset:str, ext:str, owner:str, repo:str) -> pathlib.Path:
    """
    Checks if gtest is available, or fetches it and returns the path to the library
    """
    curl_command = (
        "curl",
        "-L",
        f"-o{asset}.{ext}",
        f"https://github.com/{owner}/{repo}/releases/download/v1.2.3/{asset}.{ext}",
    )
    result = subprocess.run(curl_command)
    if result.returncode != 0:
        raise RuntimeError(f"Failed to fetch {asset} from GitHub: {result.stderr}")
    return pathlib.Path(f"{asset}.{ext}")

if __name__ == "__main__":
    _get_github_release()

    import asyncio
    # with tempfile.TemporaryDirectory() as temp_dir:
    temp_dir = pathlib.Path("./build/cpp")
    temp_dir.mkdir(parents=True, exist_ok=True)
    output_path = temp_dir / "test_binary"
    
    exe = asyncio.run(_compile_cpp("int main() { return 0; }", output_path))
    print(f"Compiled binary: {exe}")
    exe_out = subprocess.run((str(exe), ))
    exe_out.check_returncode()
