"""PyInstaller entry point (absolute import works outside a package)."""
from cyclop_windows import startup

startup.mark("python")
from cyclop_windows.app import main  # noqa: E402

if __name__ == "__main__":
    main()
