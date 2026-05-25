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
- name: dpo-v2
  results: []
---

<!-- This model card has been generated automatically according to the information the Trainer had access to. You
should probably proofread and complete it, then remove this comment. -->

# dpo-v2

This model is a fine-tuned version of [Qwen/Qwen2.5-7B-Instruct](https://huggingface.co/Qwen/Qwen2.5-7B-Instruct) on the dpo_multi_round_v2_train dataset.
It achieves the following results on the evaluation set:
- Loss: 0.0147
- Rewards/chosen: 10.9678
- Rewards/rejected: 2.4599
- Rewards/accuracies: 1.0
- Rewards/margins: 8.5079
- Logps/chosen: -307.9282
- Logps/rejected: -64.5850
- Logits/chosen: -0.1770
- Logits/rejected: -0.3520

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
- eval_batch_size: 2
- seed: 42
- gradient_accumulation_steps: 8
- total_train_batch_size: 8
- optimizer: Use OptimizerNames.ADAMW_TORCH with betas=(0.9,0.999) and epsilon=1e-08 and optimizer_args=No additional optimizer arguments
- lr_scheduler_type: cosine
- lr_scheduler_warmup_steps: 0.1
- num_epochs: 2.5

### Training results

| Training Loss | Epoch  | Step | Validation Loss | Rewards/chosen | Rewards/rejected | Rewards/accuracies | Rewards/margins | Logps/chosen | Logps/rejected | Logits/chosen | Logits/rejected |
|:-------------:|:------:|:----:|:---------------:|:--------------:|:----------------:|:------------------:|:---------------:|:------------:|:--------------:|:-------------:|:---------------:|
| 0.0279        | 0.5155 | 50   | 0.0356          | 11.0571        | 3.3981           | 0.9896             | 7.6591          | -307.0347    | -55.2027       | -0.1693       | -0.3447         |
| 0.0245        | 1.0309 | 100  | 0.0218          | 11.0310        | 2.8776           | 1.0                | 8.1534          | -307.2957    | -60.4074       | -0.1773       | -0.3528         |
| 0.0134        | 1.5464 | 150  | 0.0165          | 10.9752        | 2.5781           | 1.0                | 8.3971          | -307.8546    | -63.4027       | -0.1774       | -0.3534         |
| 0.0122        | 2.0619 | 200  | 0.0150          | 10.9809        | 2.4672           | 1.0                | 8.5137          | -307.7975    | -64.5119       | -0.1761       | -0.3513         |
| 0.0089        | 2.5052 | 243  | 0.0147          | 10.9678        | 2.4599           | 1.0                | 8.5079          | -307.9282    | -64.5850       | -0.1770       | -0.3520         |


### Framework versions

- PEFT 0.18.1
- Transformers 5.6.0
- Pytorch 2.11.0+cu130
- Datasets 4.0.0
- Tokenizers 0.22.2