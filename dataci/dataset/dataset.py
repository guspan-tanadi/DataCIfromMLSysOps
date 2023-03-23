#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Author: Li Yuanming
Email: yuanmingleee@gmail.com
Date: Mar 10, 2023
"""
import json
import subprocess
from copy import deepcopy
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd

from dataci.repo import Repo

if TYPE_CHECKING:
    from typing import Optional
    from dataci.pipeline.pipeline import Pipeline

import yaml

from .utils import generate_dataset_version_id, generate_dataset_identifier


class Dataset(object):
    from .publish import publish  # type: ignore[misc]
    from .update import update  # type: ignore[misc]
    
    def __init__(
            self,
            name,
            version=None,
            repo=None,
            dataset_files=None,
            yield_pipeline: 'Optional[Pipeline]' = None,
            parent_dataset: 'Optional[Dataset]' = None,
            log_message=None,
            id_column=None,
            size=None,
            **kwargs,
    ):
        self.name = name
        self.__published = False
        # Filled if the dataset is published
        self.version = version
        self.repo = repo or Repo()
        # Filled if the dataset is not published
        self._dataset_files = Path(dataset_files) if dataset_files else None
        self.create_date: 'Optional[datetime]' = datetime.now()
        self.yield_pipeline = yield_pipeline
        self.parent_dataset = parent_dataset
        self.log_message = log_message or ''
        # TODO: create a dataset schema and verify
        self.id_column = id_column
        # TODO: improve this get size of dataset
        if size is not None:
            self.size = size
        elif self._dataset_files and self._dataset_files.suffix == '.csv':
            self.size = len(pd.read_csv(dataset_files))
        else:
            self.size = None

        self._file_config: 'Optional[dict]' = None

    def __repr__(self):
        if all((self.name, self.version)):
            return generate_dataset_identifier(self.name, self.version[:7])
        else:
            return f'{self.name} ! Unpublished'

    @classmethod
    def from_dict(cls, config):
        from dataci.pipeline.pipeline import Pipeline

        if config['yield_pipeline']['name'] is None:
            config['yield_pipeline'] = None
        else:
            config['yield_pipeline'] = Pipeline(**config['yield_pipeline'])
        dataset_obj = cls(**config)
        dataset_obj.create_date = datetime.fromtimestamp(config['timestamp'])
        dataset_obj.__published = True
        dataset_obj._file_config = json.loads(config['file_config'])
        dataset_obj._dataset_files = (dataset_obj.repo.tmp_dir / dataset_obj.name / dataset_obj.version /
                                      config['filename'])
        # TODO: lazy load parent dataset
        dataset_obj.parent_dataset = Dataset(
            name=config['parent_dataset_name'], version=config['parent_dataset_version'])
        return dataset_obj

    def dict(self):
        yield_pipeline_dict = self.yield_pipeline.dict() if self.yield_pipeline else {'name': None, 'version': None}
        config = {
            'name': self.name,
            'timestamp': int(self.create_date.timestamp()),
            'parent_dataset_name': self.parent_dataset.name if self.parent_dataset else None,
            'parent_dataset_version': self.parent_dataset.version if self.parent_dataset else None,
            'yield_pipeline': yield_pipeline_dict,
            'log_message': self.log_message,
            'version': generate_dataset_version_id(
                self._dataset_files, self.yield_pipeline, self.log_message, self.parent_dataset
            ) if self.version is None else self.version,
            'filename': self._dataset_files.name,
            'file_config': json.dumps(self.file_config),
            'size': self.size,
            'id_column': self.id_column,
        }
        self.version = config['version']
        return config

    @property
    def dataset_files(self):
        # The dataset files is already cached
        if self._dataset_files and self._dataset_files.exists():
            return self._dataset_files
        if self.__published:
            # The dataset files need to recover from DVC
            self._dataset_files.parent.mkdir(exist_ok=True, parents=True)
            dataset_file_tracker = self._dataset_files.parent / (self._dataset_files.name + '.dvc')
            with open(dataset_file_tracker, 'w') as f:
                yaml.safe_dump(self.file_config, f)
            # dvc checkout
            cmd = ['dvc', 'checkout', '-f', str(dataset_file_tracker)]
            subprocess.run(cmd)
        return self._dataset_files

    @property
    @lru_cache(maxsize=None)
    def file_config(self):
        if self.__published:
            file_config = deepcopy(self._file_config)
            return file_config
        dvc_filename = self._dataset_files.parent / (self._dataset_files.name + '.dvc')
        if dvc_filename.exists():
            with open(dvc_filename, 'r') as f:
                file_config = yaml.safe_load(f)
            return file_config

    def __str__(self):
        return f'{self.name}@{self.version}'

    def __hash__(self):
        return hash(str(self))
    
    def __eq__(self, __o: object) -> bool:
        if isinstance(__o, type(self)):
            return str(self) == str(__o)
        return False
