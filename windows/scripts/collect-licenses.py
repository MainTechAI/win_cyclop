"""Retain available license texts from installed distribution metadata."""
from importlib.metadata import distributions
from pathlib import Path
import shutil
import sys

root = Path(sys.argv[1])
root.mkdir(parents=True, exist_ok=True)
for distribution in distributions():
    name = distribution.metadata.get('Name', 'unknown')
    for item in distribution.files or []:
        lower = str(item).lower()
        if '.dist-info/' in lower and any(part in lower for part in ('license', 'copying', 'notice')):
            source = Path(distribution.locate_file(item))
            if source.is_file():
                relative = str(item).split('.dist-info/', 1)[1]
                destination = root / name / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
