"""Explicit one-time download of English/Russian offline models."""
import argparse


def main():
    parser = argparse.ArgumentParser(description="Download Argos English↔Russian models for offline translation")
    parser.add_argument("--yes", action="store_true", help="Confirm the model downloads")
    args = parser.parse_args()
    if not args.yes:
        print("This downloads two language models from the Argos package index (potentially hundreds of MB).")
        if input("Download and install them? [y/N] ").strip().lower() != "y":
            return
    import argostranslate.package
    argostranslate.package.update_package_index()
    packages = argostranslate.package.get_available_packages()
    installed = {(p.from_code, p.to_code) for p in argostranslate.package.get_installed_packages()}
    for source, target in (("en", "ru"), ("ru", "en")):
        if (source, target) in installed:
            print(f"Already installed: {source} -> {target}")
            continue
        candidates = [p for p in packages if p.from_code == source and p.to_code == target]
        if not candidates:
            raise SystemExit(f"No {source} -> {target} model available in the current Argos index")
        package = candidates[0]
        print(f"Downloading {source} -> {target}")
        argostranslate.package.install_from_path(package.download())
    print("Models installed. Restart Cyclop if it is running.")


if __name__ == "__main__":
    main()
