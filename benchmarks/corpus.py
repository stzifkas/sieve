from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"


@dataclass(frozen=True)
class Sample:
    name: str
    category: str
    command: str
    stdout: str
    stderr: str
    exit_code: int

    @property
    def raw_chars(self) -> int:
        return len(self.stdout) + len(self.stderr)


_RUNTIME_SAMPLES = {
    "python_type_error.txt": ("python app.py", 1),
    "chained_exception.txt": ("python app.py", 1),
    "exception_group.txt": ("python app.py", 1),
    "syntax_error.txt": ("python bad.py", 1),
    "bare_module_not_found.txt": ("python -c 'import yaml'", 1),
    "deep_django_traceback.txt": ("python manage.py runserver", 1),
}

_PYTEST_SAMPLES = {
    "all_passed.txt": ("pytest tests/", 0),
    "two_failures.txt": ("pytest tests/", 1),
    "one_failure.txt": ("pytest tests/", 1),
    "collection_error.txt": ("pytest tests/", 2),
    "setup_error.txt": ("pytest tests/", 1),
    "quiet_param_failure.txt": ("python -m pytest -q", 1),
    "large_verbose.txt": ("pytest tests/ -v", 1),
}

_GENERIC_SAMPLES = {
    "long_output.txt": ("tail -n 200 app.log", 0),
}

_MYPY_SAMPLES = {
    "with_errors.txt": ("mypy src/", 1),
    "clean.txt": ("mypy src/", 0),
}

_TSC_SAMPLES = {
    "pretty_errors.txt": ("npx tsc --noEmit", 1),
    "legacy_errors.txt": ("tsc", 1),
}

_ESLINT_SAMPLES = {
    "with_errors.txt": ("npx eslint src/", 1),
}

_GCC_SAMPLES = {
    "parse_error.txt": ("gcc -c src/parser.c", 1),
}

_PIP_SAMPLES = {
    "install_failure.txt": ("pip install -r requirements.txt", 1),
    "install_success.txt": ("pip install -r requirements.txt", 0),
}


def load_samples() -> list[Sample]:
    samples: list[Sample] = []

    def add(category: str, mapping: dict[str, tuple[str, int]], on_stderr: bool) -> None:
        for fname, (cmd, code) in mapping.items():
            text = (FIXTURES / category / fname).read_text()
            stdout, stderr = ("", text) if on_stderr else (text, "")
            samples.append(Sample(fname, category, cmd, stdout, stderr, code))

    add("pytest", _PYTEST_SAMPLES, on_stderr=False)
    add("runtime", _RUNTIME_SAMPLES, on_stderr=True)
    add("generic", _GENERIC_SAMPLES, on_stderr=False)
    add("mypy", _MYPY_SAMPLES, on_stderr=False)
    add("tsc", _TSC_SAMPLES, on_stderr=True)
    add("eslint", _ESLINT_SAMPLES, on_stderr=False)
    add("gcc", _GCC_SAMPLES, on_stderr=True)
    add("pip", _PIP_SAMPLES, on_stderr=False)

    samples.sort(key=lambda s: (s.category, s.name))
    return samples
