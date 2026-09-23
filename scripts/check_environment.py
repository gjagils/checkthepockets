"""Verify the documented Python minor and locked development dependencies."""
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    expected_python = ROOT.joinpath(".python-version").read_text().strip()
    actual_python = f"{sys.version_info.major}.{sys.version_info.minor}"
    errors = []
    if actual_python != expected_python:
        errors.append(f"Python {actual_python}; expected {expected_python}")
    for filename in ("requirements.txt", "requirements-dev.txt"):
        for line in ROOT.joinpath(filename).read_text().splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            requirement = Requirement(line.strip())
            if requirement.marker and not requirement.marker.evaluate():
                continue
            try:
                installed = version(requirement.name)
            except PackageNotFoundError:
                errors.append(f"{requirement.name}: missing ({filename})")
                continue
            if installed not in requirement.specifier:
                errors.append(f"{requirement.name}: {installed}; expected {requirement.specifier}")
    if errors:
        print("Environment does not match the repository:", file=sys.stderr)
        for error in sorted(set(errors)):
            print(f"- {error}", file=sys.stderr)
        return 1
    print(f"Python {actual_python}: installed runtime and test packages match both lock files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
