# Group chat draft

大家，我这周负责的 HW6 ActionLedger MVP 代码已搭好：mock tracker、SQLite ledger、真实 OpenAI tool-calling agent，以及 lost-ack 自动演示。演示会检查任务没有重复，并验证 agent 用找回的 task ID 继续下一步。仓库：https://github.com/Cecilia1220/actionledger 。运行步骤都在 README；每个人自己在 .env 填 API key，别提交 key。之后接手的同学先 pull 最新 main，再建自己的 feature branch（例如 feature/hw7-benchmark），做完跑测试，通过后开 PR merge 回 main，下一个人再从 main 接着做。HW7 的 benchmark 和 baseline 还没有做，这周只保留 HW6 最小核心。

Before sending: confirm live demo passes and the feature branch is merged. This draft is prepared only; it has not been sent.

# Next owner

Read README, create your own virtual environment and `.env`, run the infrastructure checks, then the live model demo. Do not copy the local SQLite databases or anyone else's secrets. New benchmark work should compare the same tracker tasks with direct-call/retry baselines; preserve the current failure semantics rather than silently treating AMBIGUOUS as retryable. HW7 remains deliberately unimplemented.
