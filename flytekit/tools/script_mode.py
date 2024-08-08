import gzip
import hashlib
import importlib
import os
import shutil
import site
import sys
import tarfile
import tempfile
import typing
from pathlib import Path
from types import ModuleType
from typing import List

from flytekit import PythonFunctionTask
from flytekit.core.tracker import get_full_module_path
from flytekit.core.workflow import ImperativeWorkflow, WorkflowBase


def compress_scripts(source_path: str, destination: str, module_name: str):
    """
    Compresses the single script while maintaining the folder structure for that file.

    For example, given the follow file structure:
    .
    ├── flyte
    │   ├── __init__.py
    │   └── workflows
    │       ├── example.py
    │       ├── another_example.py
    │       ├── yet_another_example.py
    │       └── __init__.py

    Let's say you want to compress `example.py`. In that case we specify the the full module name as
    flyte.workflows.example and that will produce a tar file that contains only that file alongside
    with the folder structure, i.e.:

    .
    ├── flyte
    │   ├── __init__.py
    │   └── workflows
    │       ├── example.py
    │       └── __init__.py

    Note: If `example.py` didn't import tasks or workflows from `another_example.py` and `yet_another_example.py`, these files were not copied to the destination..

    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        destination_path = os.path.join(tmp_dir, "code")
        add_imported_modules_from_source(source_path, destination_path, list(sys.modules.values()))

        tar_path = os.path.join(tmp_dir, "tmp.tar")
        with tarfile.open(tar_path, "w") as tar:
            tmp_path: str = os.path.join(tmp_dir, "code")
            files: typing.List[str] = os.listdir(tmp_path)
            for ws_file in files:
                tar.add(os.path.join(tmp_path, ws_file), arcname=ws_file, filter=tar_strip_file_attributes)
        with gzip.GzipFile(filename=destination, mode="wb", mtime=0) as gzipped:
            with open(tar_path, "rb") as tar_file:
                gzipped.write(tar_file.read())


# Takes in a TarInfo and returns the modified TarInfo:
# https://docs.python.org/3/library/tarfile.html#tarinfo-objects
# intended to be passed as a filter to tarfile.add
# https://docs.python.org/3/library/tarfile.html#tarfile.TarFile.add
def tar_strip_file_attributes(tar_info: tarfile.TarInfo) -> tarfile.TarInfo:
    # set time to epoch timestamp 0, aka 00:00:00 UTC on 1 January 1970
    # note that when extracting this tarfile, this time will be shown as the modified date
    tar_info.mtime = 0

    # user/group info
    tar_info.uid = 0
    tar_info.uname = ""
    tar_info.gid = 0
    tar_info.gname = ""

    # stripping paxheaders may not be required
    # see https://stackoverflow.com/questions/34688392/paxheaders-in-tarball
    tar_info.pax_headers = {}

    return tar_info


def add_imported_modules_from_source(source_path: str, destination: str, modules: List[ModuleType]):
    """Copies modules into destination that are in modules. The module files are copied only if:

    1. Not a site-packages. These are installed packages and not user files.
    2. Not in the bin. These are also installed and not user files.
    3. Does not share a common path with the source_path.
    """

    site_packages = site.getsitepackages()
    site_packages_set = set(site_packages)
    bin_directory = os.path.dirname(sys.executable)

    for mod in modules:
        try:
            mod_file = mod.__file__
        except AttributeError:
            continue

        if mod_file is None:
            continue

        # Check to see if mod_file is in site_packages of bin_directory, which are
        # installed packages & libraries that are not user files. This happens when
        # there is a virtualenv like `.venv` in the working directory.
        try:
            if os.path.commonpath(site_packages + [mod_file]) in site_packages_set:
                # Do not upload files from site-packages
                continue

            if os.path.commonpath([bin_directory, mod_file]) == bin_directory:
                # Do not upload from the bin directory
                continue

        except ValueError:
            # ValueError is raised by windows if the paths are not from the same drive
            # If the files are not in the same drive, then mod_file is not
            # in the site-packages or bin directory.
            pass

        try:
            common_path = os.path.commonpath([mod_file, source_path])
            if common_path != source_path:
                # Do not upload files that do not share a common directory with the source
                continue
        except ValueError:
            # ValueError is raised by windows if the paths are not from the same drive
            # If they are not in the same directory, then they do not share a common path,
            # so we do not upload the file.
            continue

        relative_path = os.path.relpath(mod_file, start=source_path)
        new_destination = os.path.join(destination, relative_path)

        os.makedirs(os.path.dirname(new_destination), exist_ok=True)
        shutil.copy(mod_file, new_destination)


def hash_file(file_path: typing.Union[os.PathLike, str]) -> (bytes, str, int):
    """
    Hash a file and produce a digest to be used as a version
    """
    h = hashlib.md5()
    l = 0

    with open(file_path, "rb") as file:
        while True:
            # Reading is buffered, so we can read smaller chunks.
            chunk = file.read(h.block_size)
            if not chunk:
                break
            h.update(chunk)
            l += len(chunk)

    return h.digest(), h.hexdigest(), l


def _find_project_root(source_path) -> str:
    """
    Find the root of the project.
    The root of the project is considered to be the first ancestor from source_path that does
    not contain a __init__.py file.

    N.B.: This assumption only holds for regular packages (as opposed to namespace packages)
    """
    # Start from the directory right above source_path
    path = Path(source_path).parent.resolve()
    while os.path.exists(os.path.join(path, "__init__.py")):
        path = path.parent
    return str(path)
