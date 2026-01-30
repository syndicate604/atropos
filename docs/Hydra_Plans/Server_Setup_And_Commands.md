 Thw Two Training Box Server Setup

 The VLLM server only (do not run training on this just start VLLM) 

VLLM Server 34.45.239.100 training-box-20260127-072805
ssh -i ~/.ssh/gcp/ngcp_root_key root@34.45.239.100


TRAINING Server is on 35.202.149.44  training-box-01    
ssh -i ~/.ssh/gcp/ngcp_root_key -r root@35.202.149.44

 
 We server 2 models from the VLLM server 
 1 - the base model --model /root/models/Qwen2.5-7B-Instruct
 2 - the trained model --model /root/models/trained_model


root       13813  0.0  0.0   7764  1816 ?        S    03:03   0:00 bash -c killall -9 python3 2>/dev/null; nvidia-smi --query-compute-apps=pid --format=csv,noheader | xargs -r kill -9; sleep 5 && cd ~/hydra && nohup python3 example_trainer/vllm_api_server.py --model /root/models/trained_model --port 9004 --host 0.0.0.0 --dtype bfloat16 --gpu-memory-utilization 0.88 --max-model-len 8192 --max-num-seqs 16 --max-num-batched-tokens 16384 --enable-prefix-caching --trust-remote-code > /tmp/vllm_trained.log 2>&1 & sleep 35 && tail -20 /tmp/vllm_trained.log | grep -E '(Uvicorn|KV cache)'

root       13817  0.2  1.0 7955640 943108 ?      Sl   03:03   0:38 python3 example_trainer/vllm_api_server.py --model /root/models/trained_model --port 9004 --host 0.0.0.0 --dtype bfloat16 --gpu-memory-utilization 0.88 --max-model-len 8192 --max-num-seqs 16 --max-num-batched-tokens 16384 --enable-prefix-caching --trust-remote-code


 MAIN Example of run VLLM 

 {"command":"ssh -i ~/.ssh/gcp/ngcp_root_key root@34.45.239.100 \"killall -9 python3 2>/dev/null; nvidia-smi --query-compute-apps=pid --format=csv,noheader | xargs -r kill -9; sleep 5 && cd ~/hydra && nohup python3 example_trainer/vllm_api_server.py --model /root/models/Qwen2.5-7B-Instruct --port 9004 --host 0.0.0.0 --dtype bfloat16 --gpu-memory-utilization 0.88 --max-model-len 8192 --max-num-seqs 16 --max-num-batched-tokens 16384 --enable-prefix-caching --trust-remote-code > /tmp/vllm_base.log 2>&1 &\nsleep 35 && tail -20 /tmp/vllm_base.log | grep -E '(Uvicorn|KV cache)'\"","description":"Start vLLM with base model","timeout":50000}}]

 command":"ssh -i ~/.ssh/gcp/ngcp_root_key root@34.45.239.100 \"killall -9 python3 2>/dev/null; nvidia-smi --query-compute-apps=pid --format=csv,noheader | xargs -r kill -9; sleep 5 && cd ~/hydra && nohup python3 example_trainer/vllm_api_server.py --model /root/models/trained_model --port 9004 --host 0.0.0.0 --dtype bfloat16 --gpu-memory-utilization 0.88 --max-model-len 8192 --max-num-seqs 16 --max-num-batched-tokens 16384 --enable-prefix-caching --trust-remote-code > /tmp/vllm_trained.log 2>&1 &\nsleep 35 && tail -20 /tmp/vllm_trained.log | grep -E '(Uvicorn|KV cache)'\"","description":"Start vLLM with trained model","timeout":50000}}]


 MAIN Example of run TRAINERS root@training-box-01 - 35.202.149.44

We now have scripts vs manual pasting - they are on the Trainer server

SERVE Script:
/root/hydra/run_serve.sh

Usage:
./run_serve.sh [max_token_length] [total_steps]

Examples:
./run_serve.sh 512 1000    # For GRPO training with seq_len=512
./run_serve.sh 4096 1000   # For evaluation with longer sequences

EVAL Scripts:
/root/hydra/run_evals.sh

Usage:
./run_evals.sh base 3072
./run_evals.sh trained 4096

Old example code to run locally 

cd /root/hydra && rm -rf evals/trained_final && mkdir -p evals/trained_final && nohup python3 environments/hydra/secure_code_review_env.py evaluate   --openai.base_url http://10.128.0.78:9004/v1   --openai.model_name Qwen/Qwen2.5-7B-Instruct   --openai.server_type vllm   --env.tokenizer_name Qwen/Qwen2.5-7B-Instruct  --env.max_token_length 4096  --env.data_dir_to_save_evals evals/trained_final   --env.use_wandb false   > /tmp/eval_trained_final2.log 2>&1 &

Old SSH command to run evals:

{"command":"ssh -i ~/.ssh/gcp/ngcp_root_key root@35.202.149.44 \"cd /root/hydra && rm -rf evals/base_final && mkdir -p evals/base_final && nohup python3 environments/hydra/secure_code_review_env.py evaluate \\\n  --openai.base_url http://10.128.0.78:9004/v1 \\\n  --openai.model_name Qwen/Qwen2.5-7B-Instruct \\\n  --openai.server_type vllm \\\n  --env.tokenizer_name Qwen/Qwen2.5-7B-Instruct \\\n --env.max_token_length 3072 \\\n --env.data_dir_to_save_evals evals/base_final \\\n  --env.use_wandb false \\\n  > /tmp/eval_base_final.log 2>&1 &\necho 'Started baseline eval (2 tasks)' && sleep 10\"","description":"Run baseline eval with 2 tasks","timeout":20000}}]
 
 Copying data between servers
 
 {"command":"scp -i ~/.ssh/gcp/ngcp_root_key ~/.ssh/gcp/ngcp_root_key root@35.202.149.44:/root/.ssh/id_rsa && ssh -i ~/.ssh/gcp/ngcp_root_key root@35.202.149.44 \"chmod 600 /root/.ssh/id_rsa && rsync -avz --progress -e 'ssh -i /root/.ssh/id_rsa -o StrictHostKeyChecking=no' /root/hydra/trained_model_checkpoints/final_model/ root@10.128.0.78:/root/models/trained_model/\" 2>&1 | tail -30","description":"Set up SSH and copy model between servers","timeout":300000}}]

 Command history and commands we ran on the VLLM Server
 
 nohup python3 example_trainer/vllm_api_server.py --model /root/models/trained_model --port 9004 --host 0.0.0.0 --dtype bfloat16 --gpu-memory-utilization 0.88 --max-model-len 8192 --max-num-seqs 16 --max-num-batched-tokens 16384 --enable-prefix-caching --trust-remote-code > /tmp/vllm_trained_v2.log 2>&1

"command":"ssh -i ~/.ssh/gcp/ngcp_root_key root@34.45.239.100 \"ps aux | grep vllm_api_server | grep -v grep | grep -q Qwen2.5-7B-Instruct && echo 'Base model running' || echo 'Need to start base model'\"","description":"Check if base model is running","timeout":5000}}
 
 "echo '=== API Log ===' && tail -20 /tmp/atropos_api.log &&    timeout: echo && echo '=== SCR Log ===' && tail -30 /tmp/scr_serve.log"   

"curl -s http://localhost:8000/ && echo && curl -s  timeout: 15s http://localhost:8000/status"

command":"ssh -i ~/.ssh/gcp/ngcp_root_key root@34.45.239.100 \"tail -30 /tmp/vllm_base.log | grep -E '(Uvicorn|KV cache|ERROR)'\"","description":"Check vLLM base model status","timeout":5000}

{"command":"ssh -i ~/.ssh/gcp/ngcp_root_key root@34.45.239.100 \"killall -9 python3 2>/dev/null; nvidia-smi --query-compute-apps=pid --format=csv,noheader | xargs -r kill -9; sleep 5 && cd ~/hydra && nohup python3 example_trainer/vllm_api_server.py --model /root/models/Qwen2.5-7B-Instruct --port 9004 --host 0.0.0.0 --dtype bfloat16 --gpu-memory-utilization 0.88 --max-model-len 8192 --max-num-seqs 16 --max-num-batched-tokens 16384 --enable-prefix-caching --trust-remote-code > /tmp/vllm_base.log 2>&1 &\nsleep 35 && tail -20 /tmp/vllm_base.log | grep -E '(Uvicorn|KV cache)'\"","description":"Start vLLM with base model","timeout":50000}}]

nohup python3 example_trainer/vllm_api_server.py --model /root/models/Qwen2.5-7B-Instruct --port 9004 --host 0.0.0.0 --dtype bfloat16 --gpu-memory-utilization 0.88 --max-model-len 8192 --max-num-seqs 16 --max-num-batched-tokens 16384 --enable-prefix-caching --trust-remote-code > /tmp/vllm_base.log 2>&1


nohup python3 example_trainer/vllm_api_server.py --model /root/models/trained_model --port 9004 --host 0.0.0.0 --dtype bfloat16 --gpu-memory-utilization 0.88 --max-model-len 8192 --max-num-seqs 16 --max-num-batched-tokens 16384 --enable-prefix-caching --trust-remote-code > /tmp/vllm_trained_v2.log 2>&1
 
nohup python3 example_trainer/vllm_api_server.py --model /root/models/trained_model --port 9004 --host 0.0.0.0 --dtype bfloat16 --gpu-memory-utilization 0.88 --max-model-len 8192 --max-num-seqs 16 --max-num-batched-tokens 16384 --enable-prefix-caching --trust-remote-code > /tmp/vllm_trained_v2.log 2>&1

command":"ssh -i ~/.ssh/gcp/ngcp_root_key root@34.45.239.100 \"ps aux | grep vllm | grep -v grep && tail -5 /tmp/vllm_trained.log\"","description":"Check vLLM trained model status","timeout":5000}}],

command":"ssh -i ~/.ssh/gcp/ngcp_root_key root@34.45.239.100 \"killall -9 python3 2>/dev/null; nvidia-smi --query-compute-apps=pid --format=csv,noheader | xargs -r kill -9; sleep 5 && cd ~/hydra && nohup python3 example_trainer/vllm_api_server.py --model /root/models/trained_model --port 9004 --host 0.0.0.0 --dtype bfloat16 --gpu-memory-utilization 0.88 --max-model-len 8192 --max-num-seqs 16 --max-num-batched-tokens 16384 --enable-prefix-caching --trust-remote-code > /tmp/vllm_trained.log 2>&1 &\nsleep 35 && tail -20 /tmp/vllm_trained.log | grep -E '(Uvicorn|KV cache)'\"","description":"Start vLLM with trained model","timeout":50000}}]

{"command":"ssh -i ~/.ssh/gcp/ngcp_root_key root@34.45.239.100 \"ps aux | grep vllm | grep -v grep && echo '---' && tail -10 /tmp/vllm_base.log\"","description":"Check vLLM process and logs","timeout":5000}}

Running the Trainer commands ---------------------------------------------------------

{"command":"ssh -i ~/.ssh/gcp/ngcp_root_key root@35.202.149.44 \"tail -100 /tmp/eval_base_final.log\"","description":"Check baseline eval progress","timeout":10000}}]

{"command":"for task in sqli-003 sqli-004 sqli-005 sqli-006 xss-001 xss-002 path-001 cmd-001 idor-001; do\n  scp -i ~/.ssh/gcp/ngcp_root_key -r $task root@35.202.149.44:/root/hydra/environments/hydra/tasks/\ndone && echo \"All new tasks copied to server\"","description":"Copy new tasks to server","timeout":30000}}]

{"command":"scp -i ~/.ssh/gcp/ngcp_root_key -r root@35.202.149.44:/root/hydra/environments/hydra/tasks/sqli-002 environments/hydra/tasks/ && ls environments/hydra/tasks/","description":"Copy sqli-002 from server to local","timeout":15000}}

{"command":"ssh -i ~/.ssh/gcp/ngcp_root_key root@35.202.149.44 \"ls -1 /root/hydra/environments/hydra/tasks/ | wc -l && echo '---' && ls -1 /root/hydra/environments/hydra/tasks/\"","description":"Verify tasks on server","timeout":5000}}

{"command":"ssh -i ~/.ssh/gcp/ngcp_root_key root@35.202.149.44 \"ls -1 /root/hydra/environments/hydra/tasks/ | wc -l && echo '---' && ls -la /root/hydra/environments/hydra/tasks/\"","description":"Count and list tasks in folder","timeout":5000}

{"command":"ssh -i ~/.ssh/gcp/ngcp_root_key root@35.202.149.44 \"\necho '=== FAILURE SCORES BREAKDOWN ===' \necho 'BASE MODEL:'\ncat /root/hydra/evals/base_final/samples.jsonl | jq -r '{task: .task_id, reason: .failure_reason, response: .response[:200]}' \necho\necho 'TRAINED MODEL:'\ncat /root/hydra/evals/trained_final/samples.jsonl | jq -r '{task: .task_id, reason: .failure_reason, response: .response[:200]}'\n\"","description":"Get detailed breakdown","timeout":10000}}],

{"command":"ssh -i ~/.ssh/gcp/ngcp_root_key root@35.202.149.44 \"tail -100 /tmp/eval_trained_final.log\"","description":"Check trained eval progress","timeout":10000}}

{"command":"ssh -i ~/.ssh/gcp/ngcp_root_key root@35.202.149.44 \"cd /root/hydra && rm -rf evals/trained_final && mkdir -p evals/trained_final && nohup python3 environments/hydra/secure_code_review_env.py evaluate \\\n  --openai.base_url http://10.128.0.78:9004/v1 \\\n  --openai.model_name Qwen/Qwen2.5-7B-Instruct \\\n  --openai.server_type vllm \\\n  --env.tokenizer_name /root/hydra/trained_model_checkpoints/final_model \\\n  --env.data_dir_to_save_evals evals/trained_final \\\n  --env.use_wandb false \\\n  > /tmp/eval_trained_final.log 2>&1 &\necho 'Started trained eval (2 tasks)' && sleep 10\"","description":"Run trained eval with 2 tasks","timeout":20000}}]

{"command":"ssh -i ~/.ssh/gcp/ngcp_root_key root@35.202.149.44 \"cd /root/hydra && rm -rf evals/base_final && mkdir -p evals/base_final && nohup python3 environments/hydra/secure_code_review_env.py evaluate \\\n  --openai.base_url http://10.128.0.78:9004/v1 \\\n  --openai.model_name Qwen/Qwen2.5-7B-Instruct \\\n  --openai.server_type vllm \\\n  --env.tokenizer_name Qwen/Qwen2.5-7B-Instruct \\\n  --env.data_dir_to_save_evals evals/base_final \\\n  --env.use_wandb false \\\n  > /tmp/eval_base_final.log 2>&1 &\necho 'Started baseline eval (2 tasks)' && sleep 10\"","description":"Run baseline eval with 2 tasks","timeout":20000}}]

-------------

Other important files

 {"command":"ssh -i ~/.ssh/gcp/ngcp_root_key root@35.202.149.44 \"ps aux | grep 'grpo.py' | grep -v grep | awk '{print \\$2}' | xargs kill -9 2>/dev/null; sleep 2 &&\ncd /root/hydra && nohup python3 /root/hydra/example_trainer/grpo.py > /tmp/grpo.log 2>&1 &\necho 'Restarted GRPO after API registration' && sleep 20\"","description":"Restart GRPO with registered API","timeout":30000}}

