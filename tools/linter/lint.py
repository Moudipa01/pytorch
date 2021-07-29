import argparse
import asyncio
import importlib
import os
import sys
from typing import List, Any

# Modify sys.path so that linter modules can be found
# Here we are appending the path to the root of pytorch to sys.path
sys.path.insert(0, "")

from tools.linter.utils.filter_helpers import filter_files
from tools.linter.utils import (
    CommandResult,
    kebab2snake,
    kebab2camel,
    Color,
    color,
    find_changed_files,
    Glob2RegexAction,
    indent,
)

# SUPPORTED_LINTERS = ["shellcheck", "flake8", "mypy", "clang-tidy", "clang-format", "misc"]
# This list is used for quickly discovering linters The names provided here are
# not used when initializing the linter. Instead, they are declared in the
# corresponding class
SUPPORTED_LINTERS = ["shellcheck", "flake8", "mypy", "clang-tidy"]


class LinterBinaryNotFound(Exception):
    def __init__(self, exe):
        self.exe = exe
        super().__init__(f"Could not find {self.exe}")


class Linter:
    name = ""
    exe = ""
    options = argparse.Namespace()

    def __init__(self):
        exists = os.access(self.exe, os.X_OK)
        if not exists:
            raise LinterBinaryNotFound(self.exe)

        # TODO check if required options are defined

    def filter_files(self, files, glob: List[str], regex: List[str]):
        return filter_files(files, glob, regex)

    def build_parser(self, parser: argparse.ArgumentParser) -> None:
        raise NotImplementedError

    async def run(self, files: List[str], options: Any = options) -> CommandResult:
        raise NotImplementedError

    def __str__(self) -> str:
        return f"{self.name} using {self.exe}"

    def __repr__(self) -> str:
        return f"{self.name} using {self.exe}"


def build_parser(linters) -> argparse.Namespace:
    parser = argparse.ArgumentParser("Run linters on PyTorch", add_help=False)

    # Setting default values here will prevent linters from overriding option values
    # For example, it doesn't make sense for a linter to override
    # --changed-only set to true because this breaks the semantics of the
    # linter running on all filtered files by default
    parser.add_argument(
        "--changed-only",
        help="Run on changes (and not the whole codebase)",
        default=False,
        action="store_true",
    )
    parser.add_argument(
        "-g",
        "--glob",
        action=Glob2RegexAction,
        help="Only lint files that match these glob patterns "
        "(see documentation for `fnmatch` for supported syntax)."
        "If a pattern starts with a - the search is negated for that pattern.",
    )
    parser.add_argument(
        "-x",
        "--regex",
        action="append",
        help="Only lint files that match these regular expressions (from the start of the filename). "
        "If a pattern starts with a - the search is negated for that pattern.",
    )
    parser.add_argument(
        "-p", "--paths", nargs="+", help="Lint only the given paths (recursively)",
    )
    parser.add_argument(
        "-v", "--verbose", nargs="+", help="Print verbose output", default=False,
    )

    subparsers = parser.add_subparsers()
    for linter in linters:
        subparser = subparsers.add_parser(
            linter.name, parents=[parser], help=f"Run {linter.name} on the codebase"
        )
        linter.build_parser(subparser)
        subparser.set_defaults(linter=linter)

    return parser


def init_linter(name: str) -> Linter:
    module_name = kebab2snake(name)
    lint_class_name = kebab2camel(name)

    module = importlib.import_module(module_name)
    Linter = module.__dict__[lint_class_name]

    return Linter()


def init_linters() -> List[Linter]:
    return [init_linter(name) for name in SUPPORTED_LINTERS]


def merge_namespaces(a, b):
    a_dict = vars(a)
    b_dict = vars(b)
    c = a_dict.copy()
    for (k, v) in b_dict.items():
        if v is not None:
            c[k] = v
    return argparse.Namespace(**c)


async def main() -> None:
    linters = init_linters()
    parser = build_parser(linters)
    options = parser.parse_args()

    if options.changed_only:
        options.paths = await find_changed_files()

    # Run linter
    if "linter" in options:
        linters = [options.linter]

    result = CommandResult(0, "", "")
    for linter in linters:
        # We merge user-provided options into linter options
        # This allows the user to override linter-specified defaults
        linter_options = merge_namespaces(linter.options, options)

        files = await linter.filter_files(
            linter_options.paths, linter_options.glob, linter_options.regex
        )

        # print(files)

        intermediate_result = await linter.run(files, linter_options)
        if intermediate_result.failed():
            print(color(f"fail: {linter.name}", Color.red))
            print(indent(repr(intermediate_result), 4))
        else:
            print(color(f"pass: {linter.name}", Color.green))
        result += intermediate_result

    sys.exit(result.returncode)


if __name__ == "__main__":
    try:
        asyncio.get_event_loop().run_until_complete(main())
    except Exception as e:
        # TODO
        print(f"Error! Could not find {e.exe}")
        readme_path = os.path.join(os.path.dirname(__file__), "README.md")
        print(f"Follow the installation instructions in {readme_path}")
        sys.exit(-1)
