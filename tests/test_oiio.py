import pytest
import os
import shutil
import subprocess
import platform
import logging

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


@pytest.fixture
def work_dir():
    td = "./tests/work_dir"
    if not os.path.exists(td):
        os.mkdir(td)
    return td


@pytest.fixture
def oiiotool(work_dir):
    plat = platform.system().lower()
    if not os.path.exists(os.path.join(work_dir, OIIO_DIR)):
        os.mkdir(os.path.join(work_dir, OIIO_DIR))
    if not os.path.exists(os.path.join(work_dir, "results")):
        os.mkdir(os.path.join(work_dir, "results"))
    if not os.path.exists(os.path.join(work_dir, OIIO_DIR, "bin")):
        from create_package import OIIO_SOURCES

        url = OIIO_SOURCES[plat]["url"]
        archive = os.path.basename(url)

        if not os.path.exists(os.path.join(work_dir, archive)):
            status = subprocess.run(
                [
                    "curl",
                    "-L",
                    OIIO_SOURCES[plat]["url"],
                    "--output",
                    os.path.join(work_dir, archive),
                ],
                check=True,
            )
            if status.returncode != 0:
                raise RuntimeError("Failed to download OIIO tools")

        if archive.endswith(".zip"):
            status = subprocess.run(
                [
                    "unzip",
                    os.path.join(work_dir, archive),
                    "-d",
                    os.path.join(work_dir, OIIO_DIR),
                ],
                check=True,
            )
            if status.returncode != 0:
                raise RuntimeError("Failed to unzip OIIO tools")
        else:
            status = subprocess.run(
                [
                    "tar",
                    "-xzf",
                    os.path.join(work_dir, archive),
                    "-C",
                    os.path.join(work_dir, OIIO_DIR),
                ],
                check=True,
            )
            if status.returncode != 0:
                raise RuntimeError("Failed to untar OIIO tools")

    return os.path.join(
        work_dir,
        OIIO_DIR,
        "bin",
        "oiiotool.exe" if plat == "windows" else "oiiotool",
    )


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
