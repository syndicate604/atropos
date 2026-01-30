import atexit
import json
import math
import os
import random
import shutil
import string
import subprocess
import time
from typing import List, Optional, Tuple

import numpy as np
import requests
import torch
import torch.nn.functional as F
import wandb  # Added for logging
from pydantic import BaseModel, Field
from tenacity import retry, stop_after_attempt, wait_exponential
from torch.optim import AdamW
from transformers import AutoModelForCausalLM, AutoTokenizer

# Global variable to keep track of the vLLM process
vllm_process = None


def cleanup_vllm():
    global vllm_process
    if vllm_process:
        print("\nTerminating vLLM process...")
        vllm_process.terminate()
        try:
            vllm_process.wait(timeout=5)  # Wait a bit for graceful shutdown
            print("vLLM process terminated.")
        except subprocess.TimeoutExpired:
            print("vLLM process did not terminate gracefully, killing.")
            vllm_process.kill()
            vllm_process.wait()
            print("vLLM process killed.")
        vllm_process = None


# Register the cleanup function to be called on script exit
atexit.register(cleanup_vllm)


class TrainingConfig(BaseModel):
    """
    Training details, model, etc
    """

    model_name: str = Field(..., description="Name of the base model to train")
    lr: float = Field(1e-6, description="Learning rate for the optimizer")
    optimizer: str = Field(
        "paged_adamw8bit",
        description="Optimizer to use: adamw | adamw8bit | paged_adamw8bit",
    )
    training_steps: int = Field(
        25, description="Number of training steps"
    )  # Renamed from epochs
    kl_coef: float = Field(
        0.1, description="KL divergence coefficient for reference model anchoring"
    )
    batch_size: int = Field(
        2, description="Batch size for training (will be handled by get_data)"
    )
    seq_len: int = Field(2048, description="Sequence length for training")
    gradient_accumulation_steps: int = Field(
        16, description="Number of gradient accumulation steps"
    )
    device: str = Field(
        "cuda" if torch.cuda.is_available() else "cpu", description="Device to train on"
    )
    save_path: str = Field(
        "trained_model_checkpoints", description="Base path to save model checkpoints"
    )
    vllm_restart_interval: int = Field(
        3, description="Restart vLLM every N training steps"
    )
    vllm_port: int = Field(9001, description="Port for the vLLM server")
    launch_vllm: bool = Field(
        False, description="Whether to launch and manage vLLM server (use False if vLLM is already running externally)"
    )

    # Wandb configuration
    use_wandb: bool = Field(
        False, description="Whether to use Weights & Biases for logging"
    )
    wandb_project: Optional[str] = Field(None, description="Wandb project name")
    wandb_group: Optional[str] = Field(None, description="Wandb group name")


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=15))
def register_trainer(config: TrainingConfig):
    """
    Register the trainer with the Atropos API
    """
    payload = {
        "wandb_group": config.wandb_group,
        "wandb_project": config.wandb_project,
        "batch_size": config.batch_size * config.gradient_accumulation_steps,
        "max_token_len": config.seq_len,
        "starting_step": 0,
        "checkpoint_dir": config.save_path,
        "save_checkpoint_interval": config.training_steps,
        "num_steps": config.training_steps,
    }
    print(f"Registering trainer with payload: {payload}")
    response = requests.post(
        "http://localhost:8000/register",
        json=payload,
        timeout=10,
    )
    if response.status_code != 200:
        print(f"Registration failed with status {response.status_code}: {response.text}")
    response.raise_for_status()  # Raise exception if registration failed
    print(f"✓ Trainer registered with API: {response.json()}")


@retry(stop=stop_after_attempt(60), wait=wait_exponential(multiplier=1, min=4, max=10))
def get_batch():
    data = requests.get("http://localhost:8000/batch", timeout=10).json()
    return data


def pad_data_to_good_offset(data, batch_size: int, seq_len: int):
    max_token_len = max(
        [max([len(x) for x in item["tokens"]]) for item in data["batch"]]
    )
    # Hard cap at seq_len to prevent OOM from long sequences
    max_token_len = min(max_token_len, seq_len)
    # usually 64 is a good choice to ensure nonweird scaling behavior on GPUS
    # so we pad to the nearest multiple of 64
    good_multiple = 64
    if (max_token_len - 1) % (good_multiple) != 0:
        max_token_len = math.ceil((max_token_len - 1) / (good_multiple)) * good_multiple
        token_setup_len = (
            max_token_len + 1
        )  # add 1 so we can make it causal at the proper length
    else:
        token_setup_len = max_token_len
        max_token_len = (
            max_token_len - 1
        )  # since it's causal we need to remove the last bit...
    # pad all tokens to max_token_len and add to lists
    input_ids = list()
    labels = list()
    advantages = list()
    lengths = list()
    temperatures = list()
    ref_logprobs_list = list()  # For KL penalty
    for item in data["batch"]:
        scores = item["scores"]
        scores = np.array(scores)
        # check if we have more than 1 score...
        if len(scores) > 1:
            scores = scores - scores.mean()
            scores = scores / max(scores.std(), 1e-8)
        item["scores"] = scores
        if item["overrides"] is not None:
            for i in range(len(item["overrides"])):
                if item["overrides"][i].get("set_advantage_to_zero", False):
                    item["scores"][i] = 0
        # Check if ref_logprobs is available for KL penalty
        has_ref_logprobs = item.get("ref_logprobs") is not None

        for i in range(len(item["tokens"])):
            # Truncate tokens and masks to token_setup_len before padding (prevents OOM)
            # Keep the tail (completion) instead of the head (prompt) to ensure trainable tokens
            if len(item["tokens"][i]) > token_setup_len:
                item["tokens"][i] = item["tokens"][i][-token_setup_len:]
                item["masks"][i] = item["masks"][i][-token_setup_len:]
                if has_ref_logprobs:
                    item["ref_logprobs"][i] = item["ref_logprobs"][i][-token_setup_len:]
            else:
                item["tokens"][i] = item["tokens"][i]
                item["masks"][i] = item["masks"][i]
                # ref_logprobs doesn't need explicit assignment here

            lengths.append(
                math.ceil((len(item["tokens"][i]) - 1) / (good_multiple))
                * good_multiple
            )
            label_item = np.concatenate(
                [
                    np.array(item["masks"][i]),
                    np.full(
                        max(0, token_setup_len - len(item["tokens"][i])),
                        -100,
                        dtype=np.int32,
                    ),
                ]
            )
            item["tokens"][i] = np.concatenate(
                [
                    np.array(item["tokens"][i]),
                    np.zeros(
                        max(0, token_setup_len - len(item["tokens"][i])), dtype=np.int32
                    ),
                ]
            )
            input_ids.append(item["tokens"][i][:-1])
            labels.append(label_item[1:])
            advantages.append(item["scores"][i])

            # Process ref_logprobs if available (for KL penalty)
            if has_ref_logprobs:
                # Pad ref_logprobs to token_setup_len (zeros for padding, will be masked out)
                ref_lp_item = np.concatenate([
                    np.array(item["ref_logprobs"][i], dtype=np.float32),
                    np.zeros(
                        max(0, token_setup_len - len(item["ref_logprobs"][i])),
                        dtype=np.float32
                    ),
                ])
                # Shift by 1 to align with labels (labels = masks[1:])
                ref_logprobs_list.append(ref_lp_item[1:])
            else:
                # No ref logprobs available - append zeros (will skip KL if all zeros)
                ref_logprobs_list.append(np.zeros(len(label_item[1:]), dtype=np.float32))
            # per-sample override -> group generation_params -> group_overrides - > 1.0
            # need to update docs since this lets you set the temperature for each sample from the override
            t = 1.0
            if (
                item.get("overrides")
                and i < len(item["overrides"])
                and isinstance(item["overrides"][i], dict)
                and ("temperature" in item["overrides"][i])
            ):
                t = float(item["overrides"][i]["temperature"])
            elif item.get("generation_params") and (
                "temperature" in item["generation_params"]
            ):
                t = float(item["generation_params"]["temperature"])
            elif item.get("group_overrides") and (
                "temperature" in item["group_overrides"]
            ):
                t = float(item["group_overrides"]["temperature"])
            temperatures.append(t)
    # combine all lists into tensors
    token_batches = []
    label_batches = []
    advantage_batches = []
    temperature_batches = []
    ref_logprob_batches = []
    for i in range(len(input_ids) // batch_size):
        token_batches.append(
            torch.tensor(
                np.stack(input_ids[i * batch_size : (i + 1) * batch_size], axis=0)
            )
        )
        label_batches.append(
            torch.tensor(
                np.stack(labels[i * batch_size : (i + 1) * batch_size], axis=0)
            )
        )
        advantage_batches.append(
            torch.tensor(
                np.stack(advantages[i * batch_size : (i + 1) * batch_size], axis=0)
            ).view(-1, 1)
        )
        # Temperatures: one per sample, shaped for broadcasting to [B, 1, 1]
        temperature_batches.append(
            torch.tensor(
                np.array(
                    temperatures[i * batch_size : (i + 1) * batch_size],
                    dtype=np.float32,
                )
            ).view(-1, 1, 1)
        )
        # Ref logprobs: same shape as labels for KL penalty
        ref_logprob_batches.append(
            torch.tensor(
                np.stack(ref_logprobs_list[i * batch_size : (i + 1) * batch_size], axis=0),
                dtype=torch.float32
            )
        )

    return token_batches, label_batches, advantage_batches, temperature_batches, ref_logprob_batches


def get_data(
    batch_size: int, seq_len: int
) -> List[
    Tuple[
        List[torch.Tensor], List[torch.Tensor], List[torch.Tensor], List[torch.Tensor], List[torch.Tensor]
    ]
]:
    """
    getting data from the api (returns token, label, advantage, temperature, ref_logprob batches)
    """
    batches = []
    while True:
        data = get_batch()
        if data["batch"] is not None:
            # Save the batch
            with open("temp.json", "w", encoding="utf-8") as f:
                json.dump(data, f)
            # In case the inference runs ahead of the training, we loop until we don't have any more data
            batches.append(pad_data_to_good_offset(data, batch_size, seq_len))
        elif len(batches) > 0:
            # Return the batches
            return batches
        else:
            time.sleep(1)


def train(config: TrainingConfig):
    """
    Setups and runs GRPO training, restarting vLLM periodically, with wandb logging.
    """
    global vllm_process  # Declare intention to modify the global variable

    # --- Wandb Setup ---
    if config.use_wandb:
        if not config.wandb_project:
            print("Warning: wandb_project not set, disabling wandb.")
            config.use_wandb = False
        else:
            if not config.wandb_group:
                # Set group to random 8 character string
                config.wandb_group = "".join(
                    random.choices(string.ascii_letters + string.digits, k=8)
                )
            try:
                wandb.init(
                    project=config.wandb_project,
                    group=config.wandb_group,
                    config=config.dict(),  # Log config parameters
                )
                print(
                    f"Wandb logging enabled. Run: {wandb.run.name} (Project: {config.wandb_project}) "
                )
            except Exception as e:
                print(f"Error initializing wandb: {e}. Disabling wandb.")
                config.use_wandb = False
    # --- End Wandb Setup ---

    # Initialize model and tokenizer
    tokenizer = AutoTokenizer.from_pretrained(config.model_name)
    model = AutoModelForCausalLM.from_pretrained(
        config.model_name, torch_dtype=torch.bfloat16
    )

    model.to(config.device)
    # Critical for training: KV cache adds memory and isn't used for gradient updates.
    if hasattr(model, "config"):
        model.config.use_cache = False
    model.gradient_checkpointing_enable()
    model.train()

    # Setup optimizer
    optimizer_name = config.optimizer.lower()
    if optimizer_name in {"adamw8bit", "paged_adamw8bit"}:
        try:
            import bitsandbytes as bnb  # type: ignore
        except Exception as e:
            raise RuntimeError(
                f"Requested optimizer={config.optimizer}, but bitsandbytes is not available ({e}). "
                "Install it (e.g. `pip install bitsandbytes`) or set optimizer='adamw'."
            ) from e

        optimizer_cls = (
            bnb.optim.PagedAdamW8bit
            if optimizer_name == "paged_adamw8bit"
            else bnb.optim.AdamW8bit
        )
        optimizer = optimizer_cls(model.parameters(), lr=config.lr)
        print(f"Using optimizer: {optimizer_cls.__name__} (bitsandbytes)")
    elif optimizer_name == "adamw":
        optimizer = AdamW(model.parameters(), lr=config.lr)
        print("Using optimizer: torch.optim.AdamW")
    else:
        raise ValueError(
            f"Unknown optimizer '{config.optimizer}'. Expected: adamw | adamw8bit | paged_adamw8bit"
        )

    print(
        f"Starting training for {config.training_steps} steps on device: {config.device}"
    )
    if config.launch_vllm:
        print(
            f"vLLM will be restarted every {config.vllm_restart_interval} steps on port {config.vllm_port}"
        )
    else:
        print(
            f"Using external vLLM server on port {config.vllm_port} (launch_vllm=False)"
        )

    os.makedirs(config.save_path, exist_ok=True)  # Ensure base save directory exists
    register_trainer(config)

    # Init vllm
    if config.launch_vllm:
        vllm_command = [
            "python",
            "-m",
            "vllm.entrypoints.openai.api_server",
            "--model",
            config.model_name,
            "--port",
            str(config.vllm_port),
            "--dtype",
            "auto",
            "--gpu-memory-utilization",
            "0.45",
            "--disable-log-requests",
        ]
        print(f"  Launching vLLM server: {' '.join(vllm_command)}")
        try:
            vllm_process = subprocess.Popen(vllm_command)
            print(f"  vLLM server launched with PID: {vllm_process.pid}")
            # Check immediate errors
            try:
                stdout, stderr = vllm_process.communicate(timeout=2)
                if vllm_process.returncode is not None and vllm_process.returncode != 0:
                    print(f"  Error starting vLLM: {stderr.decode()}")
                    vllm_process = None
                    # Maybe raise error or just warn?
                    print("  WARNING: Failed to start vLLM server after checkpoint.")
            except subprocess.TimeoutExpired:
                print("  vLLM process started (check logs for details).")
        except FileNotFoundError:
            print(
                "\n *** ERROR: 'python -m vllm...' command not found. Make sure vLLM is installed and accessible. ***\n"
            )
            # Potentially stop training or just disable further vLLM restarts
            print("  Disabling further vLLM restarts.")
            config.vllm_restart_interval = (
                config.training_steps + 1
            )  # Prevent further restarts
        except Exception as e:
            print(f"\n *** ERROR: Failed to launch vLLM: {e} ***\n")
            print("  Disabling further vLLM restarts.")
            config.vllm_restart_interval = (
                config.training_steps + 1
            )  # Prevent further restarts
    else:
        print("  Using external vLLM server (launch_vllm=False)")

    batches = list()
    step_start_times = []

    for step in range(config.training_steps):
        step_start = time.time()
        total_loss = 0

        # Enhanced logging header
        print(f"\n{'='*80}")
        print(f"Step {step+1}/{config.training_steps} ({(step+1)/config.training_steps*100:.1f}%)")
        print(f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*80}")
        total_pos_logp = 0
        total_neg_logp = 0
        total_logp = 0
        total_pos = 0
        total_neg = 0

        # Accumulate advantage stats across microbatches (GPU tensors for efficiency)
        adv_sum = torch.tensor(0.0, device=config.device)
        adv_sumsq = torch.tensor(0.0, device=config.device)
        adv_count = 0
        num_microbatches = 0

        # Track valid tokens on GPU (no per-microbatch sync)
        valid_tokens = torch.tensor(0.0, device=config.device)
        if len(batches) == 0:
            batches = get_data(config.batch_size, config.seq_len)
        token_batches, label_batches, advantage_batches, temperature_batches, ref_logprob_batches = (
            batches.pop(0)
        )
        # Terminate existing vLLM process if running
        if config.launch_vllm:
            if (
                step + 1
            ) % config.vllm_restart_interval == 0 or step == config.training_steps - 1:  # Also restart/save on last step
                # Terminate existing vLLM process if running
                if vllm_process:
                    print("  Terminating existing vLLM process...")
                    vllm_process.terminate()
                    try:
                        vllm_process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        print(
                            "  Existing vLLM process did not terminate gracefully, killing."
                        )
                        vllm_process.kill()
                        vllm_process.wait()
                    vllm_process = None
        for tokens, labels, advantages, temperatures, ref_logprobs in zip(
            token_batches, label_batches, advantage_batches, temperature_batches, ref_logprob_batches
        ):

            tokens, labels, advantages, ref_logprobs = (
                tokens.to(config.device),
                labels.to(config.device),
                advantages.to(config.device),
                ref_logprobs.to(config.device),
            )

            # Forward pass
            # User specified that tokens/labels are already prepared by get_data
            outputs = model(tokens)  # Assuming model just needs tokens
            logits = outputs.logits  # Assuming this is the structure
            # temp scaled logits before cross entropy (clamp to prevent zero division or just ignore 0 temps?)
            t = temperatures.to(logits.device, logits.dtype)
            t = torch.where(t <= 0, torch.ones_like(t), t)
            logits = logits / t

            # Calculate GRPO loss (reverting to user's previous logic)
            # User stated ignore_index is -100 and tokens/labels are aligned by get_data
            # Assuming logits correspond directly to labels indices (no shift needed here)
            logp_per_token = -F.cross_entropy(
                logits.view(-1, logits.size(-1)),  # Flatten logits
                labels.view(-1),  # Flatten labels
                reduction="none",
                ignore_index=-100,  # User specified ignore index
            ).view(
                labels.shape
            )  # Reshape back to (batch, seq_len)

            # Use reference logprobs from batch for KL penalty (memory-safe approach)
            # ref_logprobs comes from rollout generation (inference_logprobs)
            ref_logp_per_token = ref_logprobs  # Already aligned with labels

            # Masking based on labels != -100
            mask = (labels != -100).float()
            with torch.no_grad():
                pos = (advantages > 0).float()
                neg = (advantages <= 0).float()
                mask = mask.to(logp_per_token.dtype)
                mask_sum = mask.sum(dim=-1).clamp_min(1e-8)
                avg_logp = (logp_per_token * mask).sum(dim=-1) / mask_sum
                pos_logp = (logp_per_token * pos).mean().item()
                neg_logp = (logp_per_token * neg).mean().item()
                total_pos_logp += pos_logp
                total_neg_logp += neg_logp
                total_logp += avg_logp
                total_pos += pos.sum().item()
                total_neg += neg.sum().item()

            # GRPO loss with KL penalty
            grpo_loss_term = torch.exp(logp_per_token - logp_per_token.detach())
            # Clamp denominator to prevent NaNs when all labels are -100
            mask_denom = mask.sum(-1).clamp_min(1e-8)
            grpo_loss = (
                ((-grpo_loss_term * mask).sum(-1) / mask_denom)
                * advantages.to(logp_per_token.device)
            ).mean() / config.gradient_accumulation_steps

            # KL divergence penalty (keeps policy close to reference)
            # Only apply if ref_logprobs is present (non-zero)
            # Check if ref_logprobs is valid in completion positions (mask out prompt sentinels)
            ref_is_valid = ((ref_logp_per_token * mask).abs() > 1e-6).any()

            if ref_is_valid:
                # KL(policy || ref) = logp_policy - logp_ref
                kl_div = (logp_per_token - ref_logp_per_token) * mask
                kl_penalty = (kl_div.sum(-1) / mask_denom).mean() / config.gradient_accumulation_steps
            else:
                # No valid ref logprobs - skip KL penalty for this batch
                kl_penalty = torch.tensor(0.0, device=config.device)

            # Combined loss: GRPO + KL penalty
            total_batch_loss = grpo_loss + config.kl_coef * kl_penalty
            total_batch_loss.backward()
            total_loss += total_batch_loss.item()

            # Accumulate advantage stats for step summary (stay on GPU, no sync)
            adv_sum += advantages.sum()
            adv_sumsq += (advantages ** 2).sum()
            adv_count += advantages.numel()
            num_microbatches += 1

            # Track valid tokens on GPU (no sync)
            valid_tokens += mask.sum()
        grad_norm = torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=0.5)
        optimizer.step()
        optimizer.zero_grad()
        if total_pos > 0:
            total_pos_logp /= total_pos
        if total_neg > 0:
            total_neg_logp /= total_neg
        # --- Wandb Logging ---
        if config.use_wandb:
            wandb.log(
                {
                    "train/loss": total_loss,
                    "train/learning_rate": optimizer.param_groups[0]["lr"],
                    "train/grad_norm": grad_norm.item(),
                    "train/pos_logp": total_pos_logp,
                    "train/neg_logp": total_neg_logp,
                    "train/logp": total_logp,
                },
                step=step + 1,
            )
        # --- End Wandb Logging ---

        # Enhanced step summary
        step_time = time.time() - step_start
        step_start_times.append(step_time)

        # Calculate memory usage
        if torch.cuda.is_available():
            mem_allocated = torch.cuda.memory_allocated() / 1024**3  # GB
            mem_reserved = torch.cuda.memory_reserved() / 1024**3  # GB
            mem_str = f"GPU: {mem_allocated:.2f}GB allocated, {mem_reserved:.2f}GB reserved"
        else:
            mem_str = "CPU mode"

        # Calculate ETA
        avg_step_time = sum(step_start_times[-10:]) / len(step_start_times[-10:])  # Average of last 10 steps
        remaining_steps = config.training_steps - (step + 1)
        eta_seconds = avg_step_time * remaining_steps
        eta_str = time.strftime('%H:%M:%S', time.gmtime(eta_seconds))

        # Calculate step-level loss
        # Simple average across microbatches (what we optimize)
        avg_loss = total_loss / max(num_microbatches, 1)

        # Note: total_loss already incorporates mask weighting within each microbatch
        # via the (loss * mask).sum() / mask.sum() pattern in grpo_loss_term
        # So avg_loss is already approximately token-weighted

        # Calculate step-level advantage stats (single GPU→CPU sync for all metrics)
        if adv_count > 0:
            # Compute mean and variance on GPU first
            adv_mean_t = adv_sum / adv_count
            adv_var_t = torch.clamp(adv_sumsq / adv_count - adv_mean_t ** 2, min=0.0)
            adv_std_t = torch.sqrt(adv_var_t)

            # Pack all stats into single tensor and sync once
            stats = torch.stack([adv_mean_t, adv_std_t, valid_tokens]).cpu()
            adv_mean, adv_std, total_valid_tokens = stats[0].item(), stats[1].item(), int(stats[2].item())

            adv_str = f"mean={adv_mean:.4f}, std={adv_std:.4f}, n={adv_count}"
        else:
            adv_str = "no data"
            total_valid_tokens = 0

        print(f"\n📊 Step Summary:")
        print(f"  Loss: {avg_loss:.4f} (over {num_microbatches} microbatches, {total_valid_tokens} tokens)")
        print(f"  Learning Rate: {optimizer.param_groups[0]['lr']:.2e}")
        print(f"  Gradient Norm: {grad_norm.item():.4f}")
        print(f"  Advantages: {adv_str}")
        print(f"  Pos LogP: {total_pos_logp:.4f} | Neg LogP: {total_neg_logp:.4f}")
        print(f"\n⏱️  Timing:")
        print(f"  Step Time: {step_time:.2f}s")
        print(f"  Avg Step Time (last 10): {avg_step_time:.2f}s")
        print(f"  ETA: {eta_str} ({remaining_steps} steps remaining)")
        print(f"\n💾 Memory:")
        print(f"  {mem_str}")
        print(f"  Batches in Queue: {len(batches)}")

        # --- vLLM Restart Logic (Moved AFTER optimizer step) ---
        # Note: There are much better ways of updating the policy, this is just a very simple example
        if config.launch_vllm:
            if (
                step + 1
            ) % config.vllm_restart_interval == 0 or step == config.training_steps - 1:  # Also restart/save on last step
                checkpoint_path = os.path.join(
                    config.save_path, f"step_{step+1}"
                )  # Save as step+1 since it's after step completion
                print(f"\n💾 Saving checkpoint to {checkpoint_path}...")
                save_start = time.time()
                # Ensure fresh directory for saving
                if os.path.exists(checkpoint_path):
                    shutil.rmtree(checkpoint_path)  # Remove old checkpoint if it exists
                os.makedirs(checkpoint_path, exist_ok=True)
                model.save_pretrained(checkpoint_path)
                tokenizer.save_pretrained(checkpoint_path)
                save_time = time.time() - save_start
                # Get checkpoint size
                checkpoint_size = sum(
                    os.path.getsize(os.path.join(dirpath, filename))
                    for dirpath, _, filenames in os.walk(checkpoint_path)
                    for filename in filenames
                ) / (1024**3)  # GB
                print(f"✅ Checkpoint saved ({checkpoint_size:.2f}GB in {save_time:.1f}s)")

                # Terminate existing vLLM process if running
                if vllm_process:
                    print("  Terminating existing vLLM process...")
                    vllm_process.terminate()
                    try:
                        vllm_process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        print(
                            "  Existing vLLM process did not terminate gracefully, killing."
                        )
                        vllm_process.kill()
                        vllm_process.wait()
                    vllm_process = None

                # Launch new vLLM process (only if not the very last step, maybe? depends on use case)
                # Let's still launch it on the last step for consistency, cleanup will handle it.
                vllm_command = [
                    "python",
                    "-m",
                    "vllm.entrypoints.openai.api_server",
                    "--model",
                    os.path.join(config.save_path, f"step_{step+1}"),
                    "--port",
                    str(config.vllm_port),
                    "--dtype",
                    "auto",
                    "--gpu-memory-utilization",
                    "0.45",
                    "--disable-log-requests",
                    "--served-model-name",
                    config.model_name,
                ]
                print(f"  Launching vLLM server: {' '.join(vllm_command)}")
                torch.cuda.empty_cache()
                try:
                    vllm_process = subprocess.Popen(vllm_command)
                    print(f"  vLLM server launched with PID: {vllm_process.pid}")
                    # Check immediate errors
                    try:
                        stdout, stderr = vllm_process.communicate(timeout=2)
                        if (
                            vllm_process.returncode is not None
                            and vllm_process.returncode != 0
                        ):
                            print(f"  Error starting vLLM: {stderr.decode()}")
                            vllm_process = None
                            # Maybe raise error or just warn?
                            print(
                                "  WARNING: Failed to start vLLM server after checkpoint."
                            )
                    except subprocess.TimeoutExpired:
                        print("  vLLM process started (check logs for details).")
                except FileNotFoundError:
                    print(
                        "\n *** ERROR: 'python -m vllm...' command not found. ",
                        "Make sure vLLM is installed and accessible. ***\n",
                    )
                    # Potentially stop training or just disable further vLLM restarts
                    print("  Disabling further vLLM restarts.")
                    config.vllm_restart_interval = (
                        config.training_steps + 1
                    )  # Prevent further restarts
                except Exception as e:
                    print(f"\n *** ERROR: Failed to launch vLLM: {e} ***\n")
                    print("  Disabling further vLLM restarts.")
                    config.vllm_restart_interval = (
                        config.training_steps + 1
                    )  # Prevent further restarts
        # --- End vLLM Restart Logic ---

        # Basic check if vLLM process terminated unexpectedly (outside interval check)
        if config.launch_vllm:
            if vllm_process and vllm_process.poll() is not None:
                print(
                    f"\n *** WARNING: vLLM process terminated unexpectedly (return code: {vllm_process.returncode}). ",
                    "Check vLLM logs. ***\n",
                )
                stderr_output = (
                    vllm_process.stderr.read().decode()
                    if vllm_process.stderr
                    else "No stderr"
                )
                print(f"vLLM stderr: {stderr_output}")
                vllm_process = None  # Reset so it relaunches next interval

    print("Training finished.")
    # --- Wandb Finish ---
    if config.use_wandb:
        wandb.finish()
    # --- End Wandb Finish ---
    # Final cleanup (vLLM termination) is handled by atexit

    # --- Placeholder for final model save ---
    final_save_path = os.path.join(config.save_path, "final_model")
    print(f"Saving final model to {final_save_path}")
    if os.path.exists(final_save_path):
        shutil.rmtree(final_save_path)
    os.makedirs(final_save_path, exist_ok=True)
    model.save_pretrained(final_save_path)
    tokenizer.save_pretrained(final_save_path)
    print("Final model saved.")


# Example usage (optional, can be run from another script)
if __name__ == "__main__":
    # Example: Create a config and run training
    # Replace "gpt2" with your desired model
    training_config = TrainingConfig(
        model_name="/root/models/Qwen2.5-7B-Instruct",
        training_steps=25,  # Debug run - start small to detect issues early
        batch_size=1,  # Reduced from 2 to avoid OOM
        seq_len=1024,  # Increased to 1024 for better patch generation - hard-capped in pad_data_to_good_offset
        optimizer="paged_adamw8bit",  # Avoid OOM at optimizer.step() for 7B full-parameter training
        lr=1e-6,  # Lowered from 1e-5 to prevent instability
        kl_coef=0.1,  # KL penalty to anchor policy to reference model
        vllm_restart_interval=3,  # Example interval
        vllm_port=9004,  # External vLLM server port
        launch_vllm=False,  # Use external vLLM server
        use_wandb=False,  # Disabled for now
        wandb_project="grpo-trainer-example",  # Replace with your project name
    )

    # --- End Mock ---

    train(training_config)
