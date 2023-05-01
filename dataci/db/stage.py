#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Author: Li Yuanming
Email: yuanmingleee@gmail.com
Date: May 01, 2023
"""
from . import db_connection


def create_one_stage(stage_dict):
    with db_connection:
        cur = db_connection.cursor()
        cur.execute(
            """
            INSERT INTO stage (workspace, name, version, script_path, timestamp, symbolize)
            VALUES (:workspace, :name, :version, :script_path, :timestamp, :symbolize)
            """,
            stage_dict
        )


def exist_stage(workspace, name, version):
    with db_connection:
        cur = db_connection.cursor()
        cur.execute(
            """
            SELECT EXISTS(
                SELECT 1 
                FROM   stage 
                WHERE  workspace=:workspace 
                AND    name=:name 
                AND    version=:version
            )
            """,
            {
                'workspace': workspace,
                'name': name,
                'version': version
            }
        )
        return cur.fetchone()[0]


def update_one_stage(stage_dict):
    with db_connection:
        cur = db_connection.cursor()
        cur.execute(
            """
            UPDATE stage
            SET timestamp=:timestamp, symbolize=:symbolize
            WHERE workspace=:workspace AND name=:name AND version=:version
            """,
            stage_dict
        )


def get_one_stage(workspace, name, version=None):
    with db_connection:
        cur = db_connection.cursor()
        if version is None:
            # Get the latest version
            cur.execute(
                """
                SELECT workspace, name, version, script_path, timestamp, symbolize
                FROM   stage 
                WHERE  workspace=:workspace 
                AND    name=:name
                AND    version <> 'head'
                ORDER BY version DESC
                LIMIT 1
                """,
                {
                    'workspace': workspace,
                    'name': name,
                }
            )
        else:
            cur.execute(
                """
                SELECT workspace, name, version, script_path, timestamp, symbolize
                FROM   stage 
                WHERE  workspace=:workspace 
                AND    name=:name 
                AND    version=:version
                """,
                {
                    'workspace': workspace,
                    'name': name,
                    'version': version,
                }
            )
        po = cur.fetchone()

    return dict(zip(['workspace', 'name', 'version', 'script_path', 'timestamp', 'symbolize'], po))
