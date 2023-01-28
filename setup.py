"""
Partially adopted from:
https://github.com/himbeles/ctypes-example
"""

import distutils.command.build
import sys
from distutils.command.build_ext import build_ext as build_ext_orig
from pathlib import Path

from setuptools import Extension, find_packages, setup

if sys.version_info[:2] not in ((3, 8), (3, 9), (3, 10)):
    ver = ".".join(map(str, sys.version_info[:2]))
    sys.exit(f"Unsupported Python version {ver}; supported are 3.8, 3.9 and 3.10")


def read(rel_path):
    this_path = Path(__file__).parent
    with open(this_path / rel_path) as file:
        return file.read()


def get_version(rel_path):
    for line in read(rel_path).splitlines():
        if line.startswith("__version__"):
            return line.split("=")[-1].strip()[1:-1]
    raise RuntimeError("Unable to find version string.")


def numpy_get_include():
    import numpy as np
    return np.get_include()


def numba_get_include():
    import numba as nb
    return Path(nb.__file__).parent


class CTypesExtension(Extension):
    pass


class build_ext(build_ext_orig):
    def build_extension(self, ext):
        self._ctypes = isinstance(ext, CTypesExtension)
        return super().build_extension(ext)

    def get_export_symbols(self, ext):
        if self._ctypes:
            return ext.export_symbols
        return super().get_export_symbols(ext)

    def get_ext_filename(self, ext_name):
        if self._ctypes:
            return ext_name + ".so"

        return super().get_ext_filename(ext_name)


class BuildCommand(distutils.command.build.build):
    def initialize_options(self):
        distutils.command.build.build.initialize_options(self)
        self.build_base = "rocket_fft"


with open("README.md") as file:
    long_description = file.read()

setup(
    name="rocket-fft",
    version=get_version("rocket_fft/__init__.py"),
    description="rocket-fft extends Numba by scipy.fft and numpy.fft",
    long_description_content_type="text/markdown",
    long_description=long_description,
    author="Styfen Schär",
    author_email="styfen.schaer.blog@gmail.com",
    url="https://github.com/styfenschaer/rocket-fft",
    download_url="https://github.com/styfenschaer/rocket-fft",
    packages=find_packages(),
    include_package_data=True,
    package_data={"rocket_fft": ["__init__.pyi"]},
    entry_points={
        "numba_extensions": [
            "init = rocket_fft:_init_extension",
        ],
    },
    install_requires=["numba>=0.56.0"],
    license="BSD",
    ext_modules=[
        CTypesExtension(
            "rocket_fft/_pocketfft_numba",
            sources=["rocket_fft/_pocketfft_numba.cpp"],
            extra_compile_args=["-std=c++11"],
        ),
    ],
    include_dirs=[
        numpy_get_include(),
        numba_get_include(),
    ],
    cmdclass={
        "build_ext": build_ext,
        "build": BuildCommand,
    },
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3 :: Only",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "License :: OSI Approved :: BSD License",
        "Operating System :: OS Independent",
        "Intended Audience :: Science/Research",
        "Intended Audience :: Developers",
        "Intended Audience :: Education",
        "Topic :: Scientific/Engineering",
        "Topic :: Software Development",
    ],
    keywords=["FFT", "Fourier", "Numba", "SciPy", "NumPy"],
    extras_require={
        "dev": ["scipy>=1.7.2", "pytest>=6.2.5"]
    }
)
