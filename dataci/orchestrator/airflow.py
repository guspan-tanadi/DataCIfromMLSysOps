#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Author: Li Yuanming
Email: yuanmingleee@gmail.com
Date: Jun 11, 2023
"""
import functools
import inspect
import os
import sys
from textwrap import dedent
from typing import TYPE_CHECKING

from airflow.models import DAG as _DAG
from airflow.operators.python import PythonOperator as _PythonOperator
from airflow.utils.decorators import fixup_decorator_warning_stack

from dataci.models import Workflow, Stage

if TYPE_CHECKING:
    from typing import Callable


class DAG(Workflow, _DAG):
    """A wrapper class for :code:`airflow.models.DAG`. Substituting the
    :code:`airflow.models.DAG` class with this class to provide version control
    over the DAGs.
    """
    BACKEND = 'airflow'

    name_arg = 'dag_id'

    @property
    def stages(self):
        return self.tasks

    @property
    def script(self):
        task_script = list()
        for t in self.tasks:
            task_script.append(t.script)

        if self._script is None:
            raise ValueError("Unable to infer DAG script, you should provide a script.")

        scripts = dedent(f"""
{(os.linesep * 2).join(task_script)}
        
{self._script}
        """)
        return scripts


def dag(
        dag_id: 'str' = "", **kwargs,
) -> 'Callable[[Callable], Callable[..., DAG]]':
    """
    Copy from Python dag decorator, replacing :code:`airflow.models.dag.DAG` to
    :code:`dataci.orchestrator.airflow.DAG`. Wraps a function into an Airflow DAG.
    Accepts kwargs for operator kwarg. Can be used to parameterize DAGs.

    :param dag_args: Arguments for DAG object
    :param dag_kwargs: Kwargs for DAG object.
    """

    def wrapper(f: 'Callable') -> 'Callable[..., DAG]':
        @functools.wraps(f)
        def factory(*factory_args, **factory_kwargs):
            # Generate signature for decorated function and bind the arguments when called
            # we do this to extract parameters, so we can annotate them on the DAG object.
            # In addition, this fails if we are missing any args/kwargs with TypeError as expected.
            f_sig = inspect.signature(f).bind(*factory_args, **factory_kwargs)
            # Apply defaults to capture default values if set.
            f_sig.apply_defaults()

            # Initialize DAG with bound arguments
            with DAG(
                    dag_id or f.__name__,
                    **kwargs,
            ) as dag_obj:
                # Set DAG documentation from function documentation if it exists and doc_md is not set.
                if f.__doc__ and not dag_obj.doc_md:
                    dag_obj.doc_md = f.__doc__

                # Generate DAGParam for each function arg/kwarg and replace it for calling the function.
                # All args/kwargs for function will be DAGParam object and replaced on execution time.
                f_kwargs = {}
                for name, value in f_sig.arguments.items():
                    f_kwargs[name] = dag_obj.param(name, value)

                # set file location to caller source path
                back = sys._getframe().f_back
                dag_obj.fileloc = back.f_code.co_filename if back else ""

                # Invoke function to create operators in the DAG scope.
                f(**f_kwargs)

                # Set script to source code of the decorated function
                dag_obj._script = dedent(inspect.getsource(f))

            # Return dag object such that it's accessible in Globals.
            return dag_obj

        # Ensure that warnings from inside DAG() are emitted from the caller, not here
        fixup_decorator_warning_stack(factory)
        return factory

    return wrapper


class PythonOperator(Stage, _PythonOperator):
    name_arg = 'task_id'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.__init_args = (*args, *kwargs.items())
