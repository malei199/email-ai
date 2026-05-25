---
library_name: peft
license: other
base_model: Qwen/Qwen2.5-7B-Instruct
tags:
- base_model:adapter:Qwen/Qwen2.5-7B-Instruct
- llama-factory
- lora
- transformers
pipeline_tag: text-generation
model-index:
- name: dpo-v3
  results: []
---

<!-- This model card has been generated automatically according to the information the Trainer had access to. You
should probably proofread and complete it, then remove this comment. -->

# dpo-v3

This model is a fine-tuned version of [Qwen/Qwen2.5-7B-Instruct](https://huggingface.co/Qwen/Qwen2.5-7B-Instruct) on the dpo_scheduler_v3_train dataset.
It achieves the following results on the evaluation set:
- Loss: 0.0052
- Rewards/chosen: 13.3808
- Rewards/rejected: 3.0458
- Rewards/accuracies: 1.0
- Rewards/margins: 10.3350
- Logps/chosen: -1.7561
- Logps/rejected: -78.0413
- Logits/chosen: -0.8529
- Logits/rejected: -0.8391

## Model description

More information needed

## Intended uses & limitations

More information needed

## Training and evaluation data

More information needed

## Training procedure

### Training hyperparameters

The following hyperparameters were used during training:
- learning_rate: 5e-07
- train_batch_size: 1
- eval_batch_size: 1
- seed: 42
- gradient_accumulation_steps: 8
- total_train_batch_size: 8
- optimizer: Use OptimizerNames.ADAMW_TORCH with betas=(0.9,0.999) and epsilon=1e-08 and optimizer_args=No additional optimizer arguments
- lr_scheduler_type: cosine
- lr_scheduler_warmup_steps: 0.1
- num_epochs: 3.0

### Training results

| Training Loss | Epoch  | Step | Validation Loss | Rewards/chosen | Rewards/rejected | Rewards/accuracies | Rewards/margins | Logps/chosen | Logps/rejected | Logits/chosen | Logits/rejected |
|:-------------:|:------:|:----:|:---------------:|:--------------:|:----------------:|:------------------:|:---------------:|:------------:|:--------------:|:-------------:|:---------------:|
| 0.0254        | 0.6667 | 50   | 0.0179          | 13.3885        | 4.0728           | 1.0                | 9.3157          | -1.6797      | -67.7720       | -0.8658       | -0.8489         |
| 0.0065        | 1.3333 | 100  | 0.0084          | 13.3834        | 3.3923           | 1.0                | 9.9911          | -1.7304      | -74.5766       | -0.8604       | -0.8447         |
| 0.0053        | 2.0    | 150  | 0.0056          | 13.3813        | 3.1025           | 1.0                | 10.2789         | -1.7510      | -77.4749       | -0.8612       | -0.8454         |
| 0.0042        | 2.6667 | 200  | 0.0052          | 13.3806        | 3.0310           | 1.0                | 10.3497         | -1.7581      | -78.1897       | -0.8574       | -0.8422         |
| 0.0047        | 3.0    | 225  | 0.0052          | 13.3808        | 3.0458           | 1.0                | 10.3350         | -1.7561      | -78.0413       | -0.8529       | -0.8391         |


### Framework versions

- PEFT 0.18.1
- Transformers 5.6.0
- Pytorch 2.11.0+cu130
- Datasets 4.0.0
- Tokenizers 0.22.2