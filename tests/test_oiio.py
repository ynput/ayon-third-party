import pytest
import os
from pathlib import Path
import shutil
import subprocess
import platform
import logging
import requests
import zipfile
import tarfile

OIIO_DIR = "oiio"
ALL_EXR_FILES = [
    ("ACES", "DigitalLAD.2048x1556"),
    ("ACES", "SonyF35.StillLife"),
    ("chromaticities", "Rec709_YC"),
    ("chromaticities", "Rec709"),
    ("chromaticities", "XYZ_YC"),
    ("chromaticities", "XYZ"),
    ("deep", "Balls"),
    ("deep-stereo", "Balls"),
    ("deep-stereo", "Ground"),
    ("exr-multiview", "multipart.0001"),
    ("luma-chroma", "Flowers"),
    ("multiresolution", "Kapaa"),
    ("scanlines", "Desk"),
    ("tiles", "GoldenGate"),
]

EXR_ACES_FILES = [
    ("ACES", "DigitalLAD.2048x1556"),
    ("ACES", "SonyF35.StillLife"),
]


def input_file(workdir, subdir, image, ext):
    return os.path.join(workdir, "..", "images", subdir, f"{image}.{ext}")


def output_file(workdir, testname, subdir, image, ext):
    return os.path.join(
        workdir, "results", f"{testname}.{subdir}.{image}.{ext}"
    )


def reference_file(workdir, testname, subdir, image, ext):
    return os.path.join(
        workdir, "..", "references", f"{testname}.{subdir}.{image}.ref.{ext}"
    )


def download_file(url, destination):
    try:
        response = requests.get(url)
        if response.status_code == 200:
            with open(destination, "wb") as file:
                file.write(response.content)
            logging.debug(f"File downloaded and saved to {destination}")
        else:
            raise requests.HTTPError(
                f"Failed to download {url}. "
                f"Status code: {response.status_code}"
            )
    except Exception as err:
        raise requests.ConnectionError(f"Failed to download {url}: {err}")


@pytest.fixture
def work_dir():
    td = Path("./tests/work_dir").resolve()
    if not td.exists():
        td.mkdir(parents=True)
    return td


@pytest.fixture
def oiiotool(work_dir):
    plat = platform.system().lower()
    oiio_dir = Path(work_dir) / OIIO_DIR
    if not oiio_dir.exists():
        oiio_dir.mkdir()

    results_dir = Path(work_dir) / "results"
    if not results_dir.exists():
        results_dir.mkdir()

    if not (oiio_dir / "bin").exists():
        from create_package import OIIO_SOURCES

        url = OIIO_SOURCES[plat]["url"]
        archive = os.path.basename(url)
        archive_path = Path(work_dir) / archive

        if not archive_path.exists():
            download_file(url, archive_path)

        if archive.endswith(".zip"):
            try:
                with zipfile.ZipFile(archive_path, "r") as zr:
                    zr.extractall(oiio_dir)
            except zipfile.BadZipFile as err:
                raise RuntimeError(f"Failed to unzip: {err}")
            except Exception as err:
                raise RuntimeError(f"Failed to unzip OIIO tools: {err}")
        else:
            try:
                mode = {"gz": "r:gz", "bz": "r:bz"}.get(
                    os.path.splitext(archive)[1][-2:]
                )
                with tarfile.open(archive_path, mode) as tf:  # type: ignore
                    tf.extractall(oiio_dir)
            except tarfile.TarError as err:
                raise RuntimeError(f"Failed to untar OIIO tools: {err}")

    return (Path(work_dir) / OIIO_DIR).resolve() / "bin" / (
        "oiiotool.exe" if plat == "windows" else "oiiotool")



def _compare_to_reference(oiiotool, out_file, ref_file):
    # Compare to reference image
    # use `UPDATE_REFS=1 pytest tests` to updat the reference images
    if "UPDATE_REFS" in os.environ:
        logging.info(f"Updating reference image {ref_file}")
        shutil.copy(out_file, ref_file)

    cmd = [oiiotool, ref_file, out_file, "--pdiff"]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
    )


def test_version(oiiotool):
    result = subprocess.run(
        [oiiotool, "--version"], capture_output=True, text=True
    )
    logging.debug(f"oiio version: {result.stdout}")
    if result.returncode != 0:
        logging.error(f"oiiotool error: {result.stderr}")
    assert result.returncode == 0


@pytest.mark.parametrize("subdir, image", ALL_EXR_FILES)
def test_exr_to_jpg(oiiotool, work_dir, subdir, image):
    name = "exr_to_jpg"
    in_file = input_file(work_dir, subdir, image, "exr")
    out_file = output_file(work_dir, name, subdir, image, "jpg")
    ref_file = reference_file(work_dir, name, subdir, image, "jpg")

    # convert exr to sRGB JPEG, using oiio colorspace detection heuristics.
    cmd = [oiiotool, in_file, "--ch", "0,1,2", "--autocc", "-o", out_file]
    if "deep" in subdir:
        cmd.insert(1, "--flatten")

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        logging.error(f"oiiotool error: {result.stderr}")
    assert result.returncode == 0

    # Compare to reference image
    result = _compare_to_reference(oiiotool, out_file, ref_file)
    if result.returncode != 0:
        logging.error(f"oiiotool error: {result.stderr}")
    assert result.returncode == 0


@pytest.mark.parametrize("subdir, image", EXR_ACES_FILES)
def test_aces_exr_to_jpg(oiiotool, work_dir, subdir, image):
    name = "aces_exr_to_jpg"
    in_file = input_file(work_dir, subdir, image, "exr")
    out_file = output_file(work_dir, name, subdir, image, "jpg")
    ref_file = reference_file(work_dir, name, subdir, image, "jpg")

    # convert exr to sRGB JPEG, using oiio colorspace detection heuristics.
    cmd = [
        oiiotool,
        in_file,
        "--ch",
        "0,1,2",
        "--colorconvert",
        "aces_interchange",
        "texture_paint",
        "-o",
        out_file,
    ]
    if "deep" in subdir:
        cmd.insert(1, "--flatten")

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        logging.error(f"oiiotool error: {result.stderr}")
    assert result.returncode == 0

    # Compare to reference image
    result = _compare_to_reference(oiiotool, out_file, ref_file)
    if result.returncode != 0:
        logging.error(f"oiiotool error: {result.stderr}")
    assert result.returncode == 0
