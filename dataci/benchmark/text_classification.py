#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Author: Li Yuanming
Email: yuanmingleee@gmail.com
Date: Mar 22, 2023
"""
import argparse
import time

import numpy as np
import pandas as pd
import torch
from sklearn.metrics import accuracy_score
from sklearn.preprocessing import LabelEncoder
from torch.optim import AdamW
from torch.utils.data import Dataset, DataLoader, random_split
from transformers import AutoTokenizer, AutoModelForSequenceClassification


class TextDataset(Dataset):
    def __init__(self, csv_file, id_column, text_column, label_column, tokenizer, label_encoder):
        self.data = pd.read_csv(csv_file, dtype={id_column: str})
        self.id_column = id_column
        self.text_column = text_column
        self.label_column = label_column
        self.tokenizer = tokenizer
        self.label_encoder = label_encoder
        print(self.data.head(5))

    def __len__(self):
        return len(self.data)

    def fit_label_encoder(self):
        self.label_encoder.fit(self.data[self.label_column])

    @property
    def num_classes(self):
        return len(self.label_encoder.classes_)

    def __getitem__(self, idx):
        text = self.data.iloc[idx][self.text_column]
        label_id = self.label_encoder.transform([self.data.iloc[idx][self.label_column]])[0]
        label = torch.tensor(label_id).long()
        tokens = self.tokenizer(text, padding=False, truncation=True, return_tensors='pt')
        return {
            'ids': self.data.iloc[idx][self.id_column],
            'input_ids': tokens['input_ids'].squeeze(), 'attention_mask': tokens['attention_mask'].squeeze(),
            'labels': label,
        }


def parse_args(args=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--split_ratio', type=float, default=0.95,
                        help='Ratio of training data to total data')
    parser.add_argument('--num_classes', type=int, default=4,
                        help='Number of classes in the dataset for classification.')
    parser.add_argument('--train_dataset', type=str, required=True,
                        help='Path to training dataset CSV file')
    parser.add_argument('--test_dataset', type=str, required=True,
                        help='Path to test dataset CSV file')
    parser.add_argument('--id_col', type=str, default='id',
                        help='Name of ID column in dataset')
    parser.add_argument('--text_col', type=str, default='product_name',
                        help='Name of text column in dataset')
    parser.add_argument('--label_col', type=str, default='category_lv0',
                        help='Name of label column in dataset')
    parser.add_argument('--max_train_steps_per_epoch', type=int, default=1e38,
                        help='Max number of train steps for each epoch. For debug/demo purpose.')
    parser.add_argument('--max_val_steps_per_epoch', type=int, default=1e38,
                        help='Max number of val and test steps for each epoch. For debug/demo purpose.')
    parser.add_argument('-b', '--bs', '--batch_size', type=int, default=32, dest='batch_size',
                        help='Batch size for data loader')
    parser.add_argument('-e', '--epoch', type=int, default=3,
                        help='Number of epochs for training')
    parser.add_argument('--model_name', type=str, default='bert-base-uncased',
                        help='Name of Hugging Face transformer model to use')
    parser.add_argument('--learning_rate', type=float, default=1e-5,
                        help='Learning rate for optimizer')
    parser.add_argument('--print_freq', type=int, default=100,
                        help='Printing frequency during training')
    parser.add_argument('--output_path', type=str,
                        help='Path to save trained model and results')

    # Add device argument
    parser.add_argument('--device', type=str, default='cuda' if torch.cuda.is_available() else 'cpu',
                        help='Device to use for training (cuda or cpu)')

    args = parser.parse_args(args)
    return args


def collate_fn(batch):
    max_len = max([len(item['input_ids']) for item in batch])
    new_batch = dict()
    for data in batch:
        padding_length = max_len - len(data['input_ids'])
        data['input_ids'] = torch.cat([data['input_ids'], torch.zeros(padding_length, dtype=torch.int)], dim=-1)
        data['attention_mask'] = torch.cat([data['attention_mask'], torch.zeros(padding_length, dtype=torch.int)],
                                           dim=-1)
    example = batch[0]
    for k in example.keys():
        # Pack as a PyTorch tensor
        if isinstance(example[k], torch.Tensor):
            new_batch[k] = torch.stack([item[k] for item in batch])
        else:
            # Pack as a list
            new_batch[k] = [item[k] for item in batch]

    return new_batch


def setup_dataloader(args, tokenizer, label_encoder):
    train_dataset = TextDataset(
        args.train_dataset, id_column=args.id_col, text_column=args.text_col, label_column=args.label_col,
        tokenizer=tokenizer, label_encoder=label_encoder,
    )
    train_dataset.fit_label_encoder()
    test_dataset = TextDataset(
        args.test_dataset, id_column=args.id_col, text_column=args.text_col, label_column=args.label_col,
        tokenizer=tokenizer, label_encoder=label_encoder,
    )

    # Split the dataset into training and validation sets
    train_size = int(args.split_ratio * len(train_dataset))
    val_size = len(train_dataset) - train_size
    train_dataset, val_dataset = random_split(train_dataset, [train_size, val_size])

    print(f'Train split size: {train_size}, Val split size: {val_size}')
    print(f'Test dataset size: {len(test_dataset)}')

    train_dataloader = DataLoader(train_dataset, batch_size=args.batch_size, collate_fn=collate_fn)
    val_dataloader = DataLoader(val_dataset, batch_size=args.batch_size, collate_fn=collate_fn)
    test_dataloader = DataLoader(test_dataset, batch_size=args.batch_size, collate_fn=collate_fn)
    return train_dataloader, val_dataloader, test_dataloader


def train_one_epoch(args, model, dataloader, optimizer, epoch_num, label_encoder):
    train_loss_list, train_acc_list, batch_time_list = list(), list(), list()
    train_pred_results = list()
    model.train()
    for idx, batch in enumerate(dataloader):
        batch_start_time = time.time()
        optimizer.zero_grad()
        ids = batch.pop('ids')
        for k, v in batch.items():
            batch[k] = v.to(args.device)
        labels = batch['labels']
        outputs = model(**batch)
        loss = outputs.loss
        train_loss_list.append(loss.item())
        loss.backward()
        optimizer.step()
        batch_end_time = time.time()
        batch_time_list.append(batch_end_time - batch_start_time)

        # Calculate train accuracy
        logits = outputs.logits
        probabilities = torch.softmax(logits, dim=-1).detach().cpu().numpy()
        predictions = torch.argmax(logits, dim=-1).cpu().numpy()
        labels = labels.cpu().numpy()
        acc = accuracy_score(labels, predictions)
        train_acc_list.append(acc)

        # Post-process labels and predictions
        # 1. label id to label name
        # 2. probabilities to list of label name -> probability
        labels = label_encoder.inverse_transform(labels)
        predictions = label_encoder.inverse_transform(predictions)
        probabilities = [
            dict(zip(label_encoder.classes_, prob))
            for prob in probabilities
        ]

        for id_, label, pred, prob_dict in zip(ids, labels, predictions, probabilities):
            train_pred_results.append({
                'id': id_,
                'label': label,
                'prediction': pred,
                **{f'{k}_probability': v for k, v in prob_dict.items()},
            })
            print(train_pred_results[-1])

        if idx > args.max_train_steps_per_epoch:
            # Reach the max steps for this epoch, skip to next epoch
            break
        if idx % args.print_freq == 0:
            print(f'[Epoch{epoch_num}][Step {idx}] train_loss={loss.item()}, train_acc={acc}')

    train_loss_epoch = np.average(train_loss_list).item()
    train_acc_epoch = np.average(train_acc_list).item()
    print(f"[Epoch {epoch_num}] train_loss_epoch={train_loss_epoch}, train_acc_epoch={train_acc_epoch}")
    train_metrics_dict = {
        'train_loss_epoch': train_loss_epoch,
        'train_acc_epoch': train_acc_epoch,
        'train_losses': train_loss_list,
        'train_accs': train_acc_list,
        'train_batch_times': batch_time_list,
    }

    return train_metrics_dict, train_pred_results


@torch.no_grad()
def val_one_epoch(args, model, dataloader, epoch_num, label_encoder):
    val_loss_list, val_acc_list, batch_time_list = list(), list(), list()
    val_pred_results = list()
    model.eval()
    for idx, batch in enumerate(dataloader):
        batch_start_time = time.time()
        ids = batch.pop('ids')
        for k, v in batch.items():
            batch[k] = v.to(args.device)
        labels = batch['labels']
        outputs = model(**batch)
        loss = outputs.loss
        val_loss_list.append(loss.item())
        batch_end_time = time.time()

        # Calculate train accuracy
        logits = outputs.logits
        probabilities = torch.softmax(logits, dim=-1).detach().cpu().numpy()
        predictions = torch.argmax(logits, dim=-1).cpu().numpy()
        labels = labels.cpu().numpy()
        acc = accuracy_score(labels, predictions)
        val_acc_list.append(acc)
        batch_time_list.append(batch_end_time - batch_start_time)

        # Post-process labels and predictions
        # 1. label id to label name
        # 2. probabilities to list of label name -> probability
        labels = label_encoder.inverse_transform(labels)
        predictions = label_encoder.inverse_transform(predictions)
        probabilities = [
            dict(zip(label_encoder.classes_, prob))
            for prob in probabilities
        ]

        for id_, label, pred, prob_dict in zip(ids, labels, predictions, probabilities):
            val_pred_results.append({
                'id': id_,
                'label': label,
                'prediction': pred,
                **{f'{k}_probability': v for k, v in prob_dict.items()},
            })

        if idx > args.max_val_steps_per_epoch:
            # Reach the max steps for this epoch, skip to next epoch
            break

        if idx % args.print_freq == 0:
            print(f'[Epoch{epoch_num}][Step {idx}] val_loss={loss.item()}, val_acc={acc}')

    val_loss_epoch = np.average(val_loss_list).item()
    val_acc_epoch = np.average(val_acc_list).item()
    print(f"[Epoch: {epoch_num}] val_loss_epoch={val_loss_epoch}, val_acc_epoch={val_acc_epoch}")

    val_metrics_dict = {
        'val_loss_epoch': val_loss_epoch,
        'val_acc_epoch': val_acc_epoch,
        'val_losses': val_loss_list,
        'val_accs': val_acc_list,
        'val_batch_times': batch_time_list,
    }

    return val_metrics_dict, val_pred_results


def main(args):
    # Load the tokenizer
    tokenizer = AutoTokenizer.from_pretrained(args.model_name)
    label_encoder = LabelEncoder()
    # Load dataset
    train_dataloader, val_dataloader, test_dataloader = setup_dataloader(args, tokenizer, label_encoder)
    # Load model
    model = AutoModelForSequenceClassification.from_pretrained(args.model_name, num_labels=args.num_classes)
    model = model.to(args.device)

    # Set up the optimizer
    optimizer = AdamW(model.parameters(), lr=5e-5)

    # Train the model
    for epoch in range(args.epoch):
        # train loop
        train_metrics_dict, train_pred_result = train_one_epoch(
            args, model, train_dataloader, optimizer, epoch,
            label_encoder
        )
        # Validation loop
        val_metrics_dict, val_pred_result = val_one_epoch(args, model, val_dataloader, epoch, label_encoder)

    test_metrics_dict, test_pred_result = val_one_epoch(args, model, test_dataloader, epoch_num=None)

    # Save results to CSV files
    train_df = pd.DataFrame(train_pred_result)
    train_df.to_csv('train_results.csv', index=False)
    val_df = pd.DataFrame(val_pred_result)
    val_df.to_csv('val_results.csv', index=False)
    test_df = pd.DataFrame(test_pred_result)
    test_df.to_csv('test_results.csv', index=False)


if __name__ == '__main__':
    # CUDA device
    args_ = parse_args()
    main(args_)
