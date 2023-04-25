#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Author: Li Yuanming
Email: yuanmingleee@gmail.com
Date: Feb 21, 2023
"""
import os
import subprocess

from dataci import CACHE_ROOT
from dataci.connector.s3 import connect as connect_s3, create_bucket


class Workspace(object):

    def __init__(self, name: str = None):
        if name is None:
            name = os.environ.get('DATACI_WORKSPACE', None)
        if name is None:
            raise ValueError('Workspace name is not provided and default workspace is not set.')
        self.name = str(name)
        # Workspace root
        self.root_dir = CACHE_ROOT / self.name

    @property
    def workflow_dir(self):
        return self.root_dir / 'workflow'

    @property
    def data_dir(self):
        return self.root_dir / 'data'


def create_or_use_workspace(workspace: Workspace):
    # if not workspace.root_dir.exists():
    os.makedirs(workspace.root_dir, exist_ok=True)
    os.makedirs(workspace.workflow_dir, exist_ok=True)
    os.makedirs(workspace.data_dir, exist_ok=True)
    # Create a S3 bucket for data
    fs = connect_s3()
    # Add a prefix to bucket name to avoid name conflict
    # TODO: change the prefix to account specific
    bucket_name = 'dataci-' + workspace.name
    if not fs.exists(f'/{workspace.name}'):
        create_bucket(bucket_name)
    # Mount the bucket to local data directory
    cmd = ['s3fs', f'{bucket_name}', f'{workspace.data_dir}', '-o', f'passwd_file={CACHE_ROOT / ".passwd-s3fs"}'
                                                                    '-o', 'url=https://s3.ap-southeast-1.amazonaws.com']
    subprocess.run(cmd, check=True)

    # Init database
    from dataci.db import init  # noqa

    # Set the current workspace as the default workspace
    os.environ['DATACI_WORKSPACE'] = workspace.name
