'''
Created on Aug 30, 2013

@author: James Anderson
'''

import glob
import os

from setuptools import setup, find_packages

from ez_setup import use_setuptools


# This if test prevents an infinite recursion running tests from "python setup.py test"
if __name__ == '__main__':

    use_setuptools()

    install_requires = ["nornir_pools>=1.0.2",
                        "nornir_shared>=1.0.1",
                        "nornir_imageregistration>=1.0.2",
                        "numpy>=1.7.1",
                        "scipy>=0.13.2",
                        "matplotlib"]

    packages = find_packages()

    provides = ["nornir_buildmanager"]

    dependency_links = ["git+http://github.com/jamesra/nornir-pools#egg=nornir_pools-1.0.2",
                        "git+http://github.com/jamesra/nornir-shared#egg=nornir_shared-1.0.1",
                        "git+http://github.com/jamesra/nornir-imageregistration#egg=nornir_imageregistration-1.0.2"]

    package_dir = {'nornir_buildmanager' : 'nornir_buildmanager'}
    data_files = {'nornir_buildmanager' : ['config/*.xml']}

    scripts = glob.glob(os.path.join('scripts', '*.py'))

    cmdFiles = glob.glob(os.path.join('scripts', '*.cmd'))

    scripts.extend(cmdFiles)

    entry_points = {'console_scripts': ['nornir-build = nornir_buildmanager.build:Main']}

    setup(name='nornir_buildmanager',
          version='1.0.1',
          scripts=scripts,
          description="Scripts for the construction of 3D volumes from 2D image sets.",
          author="James Anderson",
          author_email="James.R.Anderson@utah.edu",
          url="https://github.com/jamesra/nornir-buildmanager",
          packages=packages,
          package_data=data_files,
          entry_points=entry_points,
          install_requires=install_requires,
          provides=provides,
          test_suite="test",
          dependency_links=dependency_links)
