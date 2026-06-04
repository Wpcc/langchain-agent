from pathlib import Path


def get_project_root() -> str:
    """Walk up from this file until pyproject.toml is found (project root marker)."""
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "pyproject.toml").exists():
            return str(parent)
    raise RuntimeError("Cannot locate project root: no pyproject.toml found in parent directories")


def get_abs_path(relative_path: str) -> str:
    return str(Path(get_project_root()) / relative_path)


if __name__ == "__main__":
    print(get_abs_path("config/chroma.yml"))
