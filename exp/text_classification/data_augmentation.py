#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Author: Li Yuanming
Email: yuanmingleee@gmail.com
Date: May 23, 2023
"""
from pathlib import Path

import pandas as pd
import augly.text as textaugs

def read_dataset(file_name: str):
    df = pd.read_csv(file_name)
    return df


def text_augmentation(df):
    aug_function = textaugs.OneOf([
        textaugs.ReplaceSimilarUnicodeChars(),
        textaugs.SimulateTypos(),
    ])
    df['text'] = aug_function(df['text'].tolist())

    return df

def save_dataset(df, file_path):
    Path(file_path).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(file_path, index=False)


if __name__ == '__main__':
    exp_time = '2021Q1'
    data_select_strategy = 'RS'
    df = read_dataset(f'processed/data_select_{exp_time}_{data_select_strategy}.csv')
    df = text_augmentation(df)
    save_dataset(df, f'processed/data_aug_{exp_time}_aug1.csv')
