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
- name: sft-v1
  results: []
---

<!-- This model card has been generated automatically according to the information the Trainer had access to. You
should probably proofread and complete it, then remove this comment. -->

# sft-v1

This model is a fine-tuned version of [Qwen/Qwen2.5-7B-Instruct](https://huggingface.co/Qwen/Qwen2.5-7B-Instruct) on the sft_v1_timeline_train dataset.
It achieves the following results on the evaluation set:
- Loss: 0.2784

## Model description

More information needed

## Intended uses & limitations

More information needed

## Training and evaluation data

More information needed

## Training procedure

### Training hyperparameters

The following hyperparameters were used during training:
- learning_rate: 5e-05
- train_batch_size: 2
- eval_batch_size: 2
- seed: 42
- gradient_accumulation_steps: 4
- total_train_batch_size: 8
- optimizer: Use OptimizerNames.ADAMW_TORCH with betas=(0.9,0.999) and epsilon=1e-08 and optimizer_args=No additional optimizer arguments
- lr_scheduler_type: cosine
- lr_scheduler_warmup_steps: 0.1
- num_epochs: 3.0

### Training results

| Training Loss | Epoch | Step | Validation Loss |
|:-------------:|:-----:|:----:|:---------------:|
| 0.4606        | 0.4   | 25   | 0.3627          |
| 0.2950        | 0.8   | 50   | 0.3107          |
| 0.2858        | 1.192 | 75   | 0.3014          |
| 0.2559        | 1.592 | 100  | 0.2844          |
| 0.2552        | 1.992 | 125  | 0.2784          |
| 0.2266        | 2.384 | 150  | 0.2802          |
| 0.2091        | 2.784 | 175  | 0.2789          |
| 0.2056        | 3.0   | 189  | 0.2789          |


### Framework versions

- PEFT 0.18.1
- Transformers 5.6.0
- Pytorch 2.11.0+cu130
- Datasets 4.0.0
- Tokenizers 0.22.2