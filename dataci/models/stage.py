#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Author: Li Yuanming
Email: yuanmingleee@gmail.com
Date: Feb 20, 2023
"""
import abc
import json
import logging
import shutil
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from dataci.db.stage import (
    create_one_stage,
    exist_stage,
    get_one_stage_by_version,
    get_one_stage_by_tag,
    get_next_stage_version_tag,
    get_many_stages, create_one_stage_tag
)
from .base import BaseModel
from ..utils import hash_binary, hash_file, cwd

if TYPE_CHECKING:
    from os import PathLike
    from typing import Optional, Union


class Stage(BaseModel):
    """Stage mixin class.

    Attributes:
        name_arg (str): The name of the keyword arguments that is used as ID to initialize the stage.
            If subclass does not use 'name' kwargs as the ID, it should override this attribute.
    """

    name_arg = 'name'
    type_name = 'stage'

    def __init__(self, *args, input_table=None, output_table=None, **kwargs) -> None:
        name = kwargs.get(self.name_arg, None)
        if name is None:
            raise TypeError(f'__init__() missing 1 required keyword-only argument: \'{self.name_arg}\'')
        self.input_table: dict = input_table or dict()
        self.output_table: dict = output_table or dict()
        super().__init__(name, *args, **kwargs)
        self.create_date: 'Optional[datetime]' = None
        self.logger = logging.getLogger(__name__)
        self._backend = 'airflow'
        self.params = dict()
        # Original local dir of the script, it will be None if stage load from database
        self._script_dir_local: 'Optional[PathLike]' = None
        self._script_dir: 'Optional[PathLike]' = None
        self._entrypoint: 'Optional[PathLike]' = None

    @property
    def script(self):
        if self._script_dir is None:
            return None
        return {
            'path': self._script_dir,
            'entrypoint': self._entrypoint,
            'local_path': self._script_dir_local,
        }

    @abc.abstractmethod
    def test(self, *args, **kwargs):
        """Test the stage."""
        raise NotImplementedError

    def dict(self, id_only=False):
        """Get the dict representation of the stage.

        Args:
            id_only (bool): If True, only return the id of the stage, otherwise return the full dict representation.
        """
        if id_only:
            return {
                'workspace': self.workspace.name,
                'name': self.name,
                'version': self.version,
            }
        return {
            'name': self.name,
            'workspace': self.workspace.name,
            'version': self.version,
            'version_tag': self.version_tag,
            'params': self.params,
            'script': self.script,
            'timestamp': int(self.create_date.timestamp()) if self.create_date else None,
        }

    @classmethod
    def from_dict(cls, config: dict):
        from dataci.decorators.base import DecoratedOperatorStageMixin

        # TODO: make the build process more secure with sandbox / allowed safe methods
        local_dict = dict()
        with cwd(config['script']['path']):
            entry_file = Path(config['script']['entrypoint'])
            entry_module = '.'.join(entry_file.parts[:-1] + (entry_file.stem,))
            exec(
                f'import os, sys; sys.path.insert(0, os.getcwd()); from {entry_module} import *',
                local_dict, local_dict
            )
        for v in local_dict.copy().values():
            # Stage is instantiated by operator class / a function decorated by @stage
            if isinstance(v, DecoratedOperatorStageMixin):
                self = v
                break
        else:
            raise ValueError(f'Stage not found in directory:\n{config["script"]["path"]}')
        return self.reload(config)

    def __repr__(self):
        return f'{self.__class__.__name__}(name={self.workspace.name}.{self.name}@{self.version})'

    def reload(self, config=None):
        """Reload the stage from the config. If config is not provided, reload from the Database.
        """
        config = config or get_one_stage_by_version(self.workspace.name, self.name, self.fingerprint)
        if config is None:
            return self
        self.version = config['version']
        self.version_tag = config['version_tag']
        self.params = config['params']
        self.create_date = datetime.fromtimestamp(config['timestamp']) if config['timestamp'] else None
        # Manual set the script to the stage object, as the script is not available in the exec context
        if 'script' in config:
            self._script_dir = config['script']['path']
            self._entrypoint = config['script']['entrypoint']
        return self

    @property
    def fingerprint(self):
        config = self.dict()
        fingerprint_dict = {
            'workspace': config['workspace'],
            'name': config['name'],
            'params': config['params'],
            'script_dir': hash_file(config['script']['path']),
            'entrypoint': config['script']['entrypoint'],
        }
        return hash_binary(json.dumps(fingerprint_dict, sort_keys=True).encode('utf-8'))

    def save(self):
        """Save the stage to the workspace."""
        config = self.dict()
        version = self.fingerprint
        # Check if the stage is already saved
        if exist_stage(config['workspace'], config['name'], version):
            return self.reload()

        # stage is not saved
        config['version'] = version
        # Update create date
        config['timestamp'] = int(datetime.now().timestamp())

        # Save the stage script to the workspace stage directory
        save_dir = self.workspace.stage_dir / str(config['name']) / str(version)
        if save_dir.exists():
            shutil.rmtree(save_dir)
        shutil.copytree(config['script']['path'], save_dir)

        # Update the script path in the config
        config['script']['path'] = str(save_dir)
        create_one_stage(config)
        return self.reload(config)

    def publish(self):
        """Publish the stage to the workspace."""
        # Save the stage to the workspace first
        self.save()
        # Check if the stage is already published
        if self.version_tag is not None:
            self.logger.warning(f'Stage {self} is already published with version_tag={self.version_tag}')
            return self
        config = self.dict()
        config['version_tag'] = str(get_next_stage_version_tag(config['workspace'], config['name']))
        create_one_stage_tag(config)

        self.logger.info(f'Published stage: {self} with version_tag={config["version_tag"]}')

        return self.reload(config)

    @classmethod
    def get_config(cls, name, version=None):
        """Get the stage config from the workspace."""
        workspace, name, version_or_tag = cls.parse_data_model_get_identifier(name, version)
        if version_or_tag == 'latest' or version_or_tag.startswith('v'):
            config = get_one_stage_by_tag(workspace, name, version_or_tag)
        else:
            config = get_one_stage_by_version(workspace, name, version_or_tag)

        return config

    @classmethod
    def get(cls, name, version=None):
        """Get the stage from the workspace."""
        config = cls.get_config(name, version)
        if config is None:
            return

        return cls.from_dict(config)

    @classmethod
    def find(cls, stage_identifier, tree_view=False, all=False):
        """Find the stage from the workspace."""
        workspace, name, version = cls.parse_data_model_list_identifier(stage_identifier)
        stage_configs = get_many_stages(workspace, name, version, all=all)
        stages = [cls.from_dict(stage_config) for stage_config in stage_configs]
        if tree_view:
            stage_dict = defaultdict(dict)
            for stage in stages:
                stage_dict[stage.full_name][stage.version] = stage
            return stage_dict

        return stages
