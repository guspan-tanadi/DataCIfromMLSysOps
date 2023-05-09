#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Author: Li Yuanming
Email: yuanming.li@alibaba-inc.com
Date: May 08, 2023
"""
from dataci.decorators.stage import stage
from dataci.decorators.workflow import workflow


@stage()
def config_ci_runs(**context):
    from dataci.models import Workflow, Dataset, Stage

    workflow_name = context['params']['workflow']
    stage_name = context['params']['stage']
    dataset_name = context['params']['dataset']
    # Get all workflow versions
    workflows = Workflow.find(workflow_name)
    # Get all dataset versions
    dataset = Dataset.find(dataset_name)
    # Get all stage versions to be substituted
    stages = Stage.find(stage_name)

    job_configs = list()
    # Build new workflow with substituted stages
    for w in workflows:
        for s in stages:
            w.patch(s)
            w.cache()
            job_configs.append({
                'workflow': w.identifier,
                'dataset': dataset.identifier,
            })

    return job_configs


@stage()
def run(job_configs, **context):
    import re
    from dataci.models import Workflow

    ci_workflow_name = context['params']['name']
    for job_config in job_configs:
        ci_workflow = Workflow.get(ci_workflow_name)
        # Set workflow running parameters, resolve variables
        for k, v in ci_workflow.params.items():
            # Locate variable
            matched = re.match(r'{{(.*)}}', v)
            if matched:
                # Resolve variable
                v = matched.group(1)
                # TODO: Resolve variable
                if v == 'config.workflow':
                    v = job_config['workflow']
                elif v == 'config.dataset':
                    v = job_config['dataset']
                elif v == 'config.dataset.version':
                    v = job_config['dataset'].split('@')[1]
                elif v == 'config.stage':
                    v = job_config['stage']
                else:
                    raise ValueError(f'Fail to parse variable: {v}')
            ci_workflow.params[k] = v
        ci_workflow()


@workflow(
    name='official.ci_cd_trigger',
)
def trigger_ci_cd():
    config_ci_runs >> run


if __name__ == '__main__':
    trigger_ci_cd.publish()