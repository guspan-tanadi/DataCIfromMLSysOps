#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Author: Li Yuanming
Email: yuanmingleee@gmail.com
Date: Feb 20, 2023
"""
import inspect
import logging
import shutil
from abc import ABC, abstractmethod
from datetime import datetime
from typing import TYPE_CHECKING

from dataci.config import DEFAULT_WORKSPACE
from dataci.db.stage import create_one_stage, exist_stage, update_one_stage, get_one_stage, get_next_stage_version_id
from dataci.decorators.event import event
from dataci.utils import GET_DATA_MODEL_IDENTIFIER_PATTERN
from . import WORKFLOW_CONTEXT
from .base import BaseModel
from .workspace import Workspace

if TYPE_CHECKING:
    from typing import Optional

    from networkx import DiGraph

logger = logging.getLogger(__name__)


class Stage(BaseModel, ABC):
    def __init__(
            self, name: str, symbolize: str = None, **kwargs,
    ) -> None:
        super().__init__(name, **kwargs)
        self.symbolize = symbolize
        self.create_date: 'Optional[datetime]' = None
        # Output is saved after the stage is run, this is for the descendant stages to use
        self._output = None
        self._script = None

    @abstractmethod
    def run(self, *args, **kwargs):
        raise NotImplementedError('Method `run` not implemented.')

    @property
    def script(self):
        # Note: if the Stage object is created from exec, it is not able to get the source code by this function
        # Therefore, we need to manual set the script passed to exec to self._script
        if self._script is None:
            # Get the source code of the class
            try:
                source_code = inspect.getsource(self.__class__)
            except OSError:
                # If the source code is not available, the class is probably dynamically generated
                # We can get the source code from the wrapped function
                source_code = inspect.getsource(getattr(self, '__wrapped__'))
            self._script = source_code
        return self._script

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
            'script': self.script,
            'timestamp': self.create_date.timestamp() if self.create_date else None,
            'symbolize': self.symbolize,
        }

    @classmethod
    def from_dict(cls, config: dict):
        # Get script from stage code directory
        workspace = Workspace(config['workspace'])
        with (workspace.stage_dir / config['script_path']).open() as f:
            script = f.read()

        config['script'] = script
        # Build class object from script
        # TODO: make the build process more secure with sandbox / allowed safe methods
        local_dict = locals()
        # import stage
        from dataci.decorators.stage import stage
        local_dict['stage'] = stage
        exec(script, globals(), local_dict)
        for v in local_dict.copy().values():
            # Stage is instantiated by a class
            if inspect.isclass(v) and issubclass(v, Stage) and v is not Stage:
                sub_cls = v
                self = sub_cls(**config)
                break
            # Stage is instantiated by a function decorated by @stage
            elif isinstance(v, Stage):
                self = v
                break
        else:
            raise ValueError(f'Stage not found by script: {config["script_path"]}\n{script}')

        return self.reload(config)

    def add_downstream(self, stage: 'Stage'):
        dag: DiGraph = self.context.get('dag')
        if dag is None:
            raise ValueError('DAG is not set in context.')
        dag.add_edge(self, stage)

        return stage

    @property
    def context(self):
        # Get context from contextvars, this will be set within the context of a models
        return WORKFLOW_CONTEXT.get()

    @property
    def ancestors(self):
        return self.context.get('dag').predecessors(self)

    def __call__(self, *args, **kwargs):
        # Inspect run method signature
        sig = inspect.signature(self.run)
        # If context is in run method signature, pass context to run method
        if 'context' in sig.parameters:
            kwargs.update(self.context)
        outputs = self.run(*args, **kwargs)
        self._output = outputs
        return outputs

    def __rshift__(self, other):
        return self.add_downstream(other)

    def __repr__(self):
        return f'{self.__class__.__name__}(name={self.workspace.name}.{self.name})'

    def reload(self, config):
        """Reload the stage from the config."""
        self.version = config['version']
        self.create_date = datetime.fromtimestamp(config['timestamp']) if config['timestamp'] else None
        # Manual set the script to the stage object, as the script is not available in the exec context
        self._script = config['script']
        return self

    @event(name='stage_save')
    def save(self):
        """Save the stage to the workspace."""
        config = self.dict()
        # Since save, we force set the version to None
        config['version'] = None
        # Update create date
        config['timestamp'] = int(datetime.now().timestamp())

        # Save the stage script to the workspace stage directory
        save_dir = self.workspace.stage_dir / str(config['name']) / 'HEAD'
        save_file_path = save_dir / 'script.py'
        save_dir.mkdir(parents=True, exist_ok=True)

        # Update the script path in the config
        config['script_path'] = str(save_file_path.relative_to(self.workspace.stage_dir))
        if not exist_stage(config['workspace'], config['name'], config['version']):
            with open(save_file_path, 'w') as f:
                f.write(config['script'])
            create_one_stage(config)
        else:
            with open(save_file_path, 'w') as f:
                f.write(config['script'])
            update_one_stage(config)
        return self.reload(config)

    @event(name='stage_publish')
    def publish(self):
        """Publish the stage to the workspace."""
        # Save the stage to the workspace first
        self.save()
        config = self.dict()
        config['version'] = str(get_next_stage_version_id(config['workspace'], config['name']))
        # Copy the script path from save version dir to the workspace publish version dir
        publish_dir = self.workspace.stage_dir / str(config['name']) / config['version']
        save_dir = self.workspace.stage_dir / str(config['name']) / 'HEAD'
        shutil.rmtree(publish_dir)
        publish_dir.mkdir(parents=True, exist_ok=True)
        shutil.copytree(save_dir, publish_dir)

        # Update the script path in the config
        config['script_path'] = str(publish_dir / 'script.py')
        create_one_stage(config)
        return self.reload(config)

    @classmethod
    def get(cls, name, version=None):
        """Get the stage from the workspace."""
        # If version is provided along with name
        matched = GET_DATA_MODEL_IDENTIFIER_PATTERN.match(str(name))
        if not matched:
            raise ValueError(f'Invalid data identifier {name}')
        # Parse name and version
        workspace, name, version_ = matched.groups()
        workspace = workspace or DEFAULT_WORKSPACE
        # Only one version is allowed to be provided, either in name or in version
        if version and version_:
            raise ValueError('Only one version is allowed to be provided by name or version.')
        version = version or version_
        if version:
            version = str(version).lower()
            if version == 'none':
                version = None

        stage_config = get_one_stage(workspace, name, version)
        stage = cls.from_dict(stage_config)
        return stage