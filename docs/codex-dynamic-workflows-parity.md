# CodexでClaude Code Dynamic Workflows級の大量並列・動的モデル/Reasoning制御を実現する設計メモ

## 0. 要約

Codexでも、Claude CodeのDynamic Workflows / Fork / Subagent / Agent Teamに近い体験は実現可能。
ただし、実現方法は「Codexに強いsubagentをプロンプトで頼む」ではなく、**外部Workflow Runner + Codex CLI worker + Codex native multi-agent v2** の三層構成にするのが現実的。

特にCodex版では、Claude Codeのようなモデル動的選択に加えて、**taskごとの `reasoning_effort` 制御を一級パラメータにする**べき。
Codex native `spawn_agent` は `model` / `reasoning_effort` を持つが、full-history fork時にはoverrideできない制約があるため、大量並列・モデル/effort切替・worktree分離は外部runner主導にする。

---

## 1. ここまでの経緯

### 1.1 最初の問い

X投稿で示されていたClaude Code系のDynamic Workflowsのように、複数agentを大量に起動し、phaseごとに進行し、agent数・進捗・結果を見ながら作業させる体験を、Codexでも同レベルに強い機能として実現できるかを検討した。

### 1.2 参照したもの

調査・比較した対象は主に以下。

- Pi / `pi-dynamic-workflows` 系の実装
  - `agent()`
  - `parallel()`
  - `pipeline()`
  - `phase()`
  - `log()`
  - structured output
- Claude CodeのDynamic Workflows系の挙動
  - Fork
  - Subagent
  - Agent Team / Swarm / Teammate
  - TaskList / phase管理
  - Don’t Peek的なtranscript非読込設計
  - worktree isolation
  - `/workflows` 系のprogress UI
- Codex CLI / Codex Rust source
  - `codex exec`
  - `multi_agent`
  - `multi_agent_v2`
  - `spawn_agent`
  - `wait_agent`
  - `list_agents`
  - `close_agent`
  - `send_message`
  - `followup_task`
  - `fork_turns`
  - `model`
  - `reasoning_effort`

### 1.3 現時点の判断

- Piは「Workflow DSLを実行するrunner」に近い。
- Claude Codeはそこから進んで、Fork / Subagent / Team / Workflow UIを統合した「agent runtime」に近い。
- Codexは低レベルprimitiveは揃いつつあるが、Claude Code級のUXはまだ外部runnerが必要。
- Codex版の主戦略は、**Codexをworker primitiveとして扱い、workflow runtimeを外に作る**こと。

---

## 2. Pi参考からClaude Code現行機能への変化

### 2.1 Pi参考の基本形

Pi参考では、親agentが小さなworkflow scriptを書き、runnerがそれを解釈してsubagentを起動する。

典型形:

```js
phase('Discover')
const inventory = await agent('Inspect repository structure', {
  label: 'repo inventory'
})

phase('Review')
const reviews = await parallel(
  inventory.files.map(file => () =>
    agent(`Review ${file}`, { label: `review ${file}` })
  )
)

phase('Synthesize')
const final = await agent('Synthesize results:\n' + JSON.stringify(reviews), {
  label: 'final synthesis'
})
```

Piの本質:

- 小さいDSL
- 並列実行
- structured output
- phase表示
- subagentごとの独立実行

### 2.2 Claude Code側で強化されている点

Pi参考から見た大きな変化は以下。

#### 1. Workflowが一級機能化

Piは「workflow toolにscriptを渡す」形。
Claude Codeは `/workflows` やDynamic Workflowsのprogress UIを含み、phase / agent count / elapsed / token等を表示するruntimeに近い。

#### 2. ForkとSubagentの分離

Piの `agent()` は基本的にfresh subagent。
Claude Codeは以下を分けている。

- **Fork**
  - 親contextを引き継ぐ
  - prompt cacheを効かせやすい
  - 同じ問題を複数方針で探索する用途
- **Subagent**
  - zero-contextまたは狭いcontext
  - 専門roleに切る用途
  - 親context汚染を避けやすい

#### 3. Team / Swarm化

Claude Codeは単に複数agentを起動するだけでなく、agentを作成・通信・停止・削除・follow-upする方向に進んでいる。

必要なprimitive:

- create/spawn
- wait
- list
- message
- close/delete
- follow-up task
- status tracking

#### 4. TaskList / phase依存

単純な `parallel()` だけではなく、phase、dependency、completion count、失敗時のrepairなどを持つDAG runner的な設計になっている。

#### 5. Don’t Peek

大規模agent fan-outでは、子agentの全transcriptを親に読ませるとcontextが壊れる。
Claude Code系では、子の詳細ログではなく、outcome / structured resultだけを親やsynthesis agentに渡す設計が重要。

#### 6. worktree isolation

大量並列でコードを書かせる場合、同じcheckoutに複数agentが同時writeすると壊れる。
Claude Codeは `--worktree` やworkflow側の `isolation: "worktree"` を持ち、並列writeを分離しやすい。

#### 7. モデル・reasoning effortの動的選択

Claude Codeは以下のような動的選択を持つ。

- `--model`
- `/model`
- custom agent frontmatterの `model`
- `--effort`
- `/effort`
- `CLAUDE_CODE_EFFORT_LEVEL`
- `--fallback-model`

この点はPi参考よりかなり強い。
Codex版でも、単なるモデル指定だけでなく、**reasoning_effortをtask単位で制御できる設計**にする必要がある。

---

## 3. Claude Code側の整理

Claude Code側の強さは、以下の機能群が一体になっていること。

### 3.1 Dynamic Workflows

- phaseを持つ
- 複数agentをfan-outする
- progress UIがある
- agent数・phase進捗・token/cost系を表示できる
- workflow runをwatch / pause / resume / stopできる方向性

### 3.2 Fork

親contextを継承して分岐する。

向いている用途:

- 同じbugに対して複数修正案を並列探索
- architecture案の比較
- review観点の分岐
- prompt cacheを使って大きな文脈を再利用

注意点:

- contextを引き継ぐので、role特化やモデル変更とは相性が悪い場合がある
- 子のログを親に全部戻すとcontextが汚染される

### 3.3 Subagent

zero-contextまたはnarrow-contextの専門agent。

向いている用途:

- security reviewer
- test writer
- doc writer
- migration checker
- dependency inspector
- performance reviewer

### 3.4 Agent Team / Swarm

複数agentをチームとして扱う。

必要な管理対象:

- agent ID / nickname / task path
- role
- model
- effort
- status
- parent-child関係
- artifact path
- final outcome
- close/delete state

### 3.5 モデル・effort選択

Claude Codeではroleごとにモデルやeffortを変えられる。
例えば:

- scan: haiku / low
- implement: sonnet / high
- architecture: opus / max
- fallback: haiku

Codex版では、この思想を `model` と `reasoning_effort` の二軸で再現する。

---

## 4. Codex側で確認した能力

### 4.1 Codex CLI workerとしての能力

Codex CLIは `codex exec` をworker primitiveとして使える。

重要flag:

```bash
codex exec \
  --json \
  -m "$MODEL" \
  -C "$WORKDIR" \
  --output-schema "$SCHEMA" \
  -o "$OUTPUT_FILE" \
  "$PROMPT"
```

使うべき機能:

- `-m, --model`
  - worker単位のモデル指定
- `--json`
  - JSONL event stream
- `--output-schema`
  - 最終出力の構造化
- `-o`
  - 最終応答をfile保存
- `-C`
  - workerごとのworking directory指定
- `-c key=value`
  - config override
  - `reasoning_effort`系の調整に使う

### 4.2 Codex native multi_agent_v2

Codex source上、`multi_agent_v2` には以下のtoolがある。

- `spawn_agent`
- `wait_agent`
- `list_agents`
- `close_agent`
- `send_message`
- `followup_task`

`spawn_agent` の重要引数:

- `task_name`
- `message`
- `agent_type`
- `fork_turns`
- `model`
- `reasoning_effort`
- `service_tier`

### 4.3 `fork_turns`

`fork_turns` はClaude CodeのFork/Subagentに対応する重要な軸。

- `fork_turns: "all"`
  - full-history fork
  - Claude CodeのForkに近い
- `fork_turns: "none"`
  - zero-context subagent
  - Claude CodeのSubagentに近い
- `fork_turns: "3"` など
  - 直近N turnだけ引き継ぐ
  - narrow-context specialistに使える

### 4.4 Codex側の重要制約

Codex native `spawn_agent` には大事な制約がある。

**full-history fork (`fork_turns: "all"`) では、子agentだけ `model` / `reasoning_effort` / `agent_type` をoverrideできない。**

つまり:

```yaml
# これはCodex nativeでは制約に当たりやすい
fork_turns: all
model: different-model
reasoning_effort: xhigh
agent_type: reviewer
```

設計上の結論:

- full forkしたい場合
  - 親と同じmodel/effort前提
- model/effort/roleを変えたい場合
  - `fork_turns: none`
  - `fork_turns: "3"` などnarrow fork
  - または外部runnerから別 `codex exec -m ...` workerとして起動

### 4.5 `fork_turns` defaultに注意

`fork_turns` のdefaultは `all` 側に寄る。
そのため、Claude CodeのSubagent相当をCodexで再現したい場合は、明示的に以下を指定するべき。

```json
{
  "fork_turns": "none"
}
```

---

## 5. Codex版の基本方針

Codexで同等体験を作るなら、以下の三層構成にする。

```text
Codex parent / human
  -> external workflow runner / MCP server
    -> Codex CLI workers x N
      -> optional native multi_agent_v2 local fan-out
        -> structured artifacts
          -> verifier / synthesis phase
```

### 5.1 Layer 1: Workflow Runner

外部runnerが担当するもの:

- workflow DSL parse
- DAG / phase / dependency管理
- queue管理
- concurrency制御
- retry
- timeout
- budget / token / cost管理
- workerごとのgit worktree作成
- workerごとのmodel指定
- workerごとのreasoning_effort指定
- JSONL log保存
- structured output schema検証
- diff収集
- test実行
- conflict検出
- progress UI
- final synthesis起動

ここはCodex本体ではなく、外に作る。

### 5.2 Layer 2: Codex CLI Worker

1 task = 1 `codex exec` process。

workerの責務:

- 与えられたscopeだけ読む/書く
- 必要なtestを実行
- structured resultを返す
- raw transcriptはJSONLとして保存
- 最終summaryを短く保存

### 5.3 Layer 3: Codex native multi_agent_v2

worker内での小規模fan-outに使う。

向いている用途:

- reviewerを1〜3体だけ呼ぶ
- implementation worker内で小さな調査agentを呼ぶ
- 直近contextだけ渡してfollow-upする
- team風の対話を局所的に使う

向いていない用途:

- 100体以上のwrite-heavy workerを直接spawn
- global queue管理
- git worktree分離
- phase UI全体
- conflict merge管理

---

## 6. Codex版Workflow DSL案

### 6.1 YAML IRを主にする

PiのようなJS DSLは書きやすいが、model-written JSをそのまま実行するのは危険。
Codex版は、最初はYAML/JSONのWorkflow IRにするのが安全。

```yaml
version: 1
name: codex_dynamic_workflow

settings:
  max_concurrency: 32
  default_timeout_sec: 1800
  artifact_dir: .codex-flow
  dont_peek: true

models:
  fast:
    model: gpt-5.4-mini
    reasoning_effort: low
  coding:
    model: gpt-5.3-codex-spark
    reasoning_effort: high
  strongest:
    model: gpt-5.4
    reasoning_effort: xhigh

phases:
  - id: discover
    title: Discover targets
    concurrency: 16
    tasks:
      - id: file_map
        role: scout
        mode: subagent
        fork_turns: none
        model_profile: fast
        worktree: read_only
        output_schema: schemas/file_map.schema.json
        prompt: |
          Inspect the repository and identify independent implementation targets.
          Return only structured JSON.

  - id: implement
    title: Implement in isolated worktrees
    depends_on: [discover]
    concurrency: 12
    generate_tasks_from: discover.file_map.targets
    defaults:
      role: implementer
      model_profile: coding
      worktree: isolated
      output_schema: schemas/patch_result.schema.json
      verification:
        - npm test -- --runInBand
    prompt_template: |
      Implement the target below in this isolated worktree.
      Target: {{ target.id }}
      Files: {{ target.files }}
      Requirements: {{ target.requirements }}

      Return structured JSON with changed_files, tests_run, result, blockers.

  - id: verify
    title: Review and synthesize
    depends_on: [implement]
    concurrency: 4
    tasks:
      - id: final_review
        role: reviewer
        model_profile: strongest
        worktree: read_only
        dont_peek: true
        input_artifacts:
          - .codex-flow/results/**/*.json
          - .codex-flow/diffs/**/*.patch
        output_schema: schemas/final_review.schema.json
        prompt: |
          Review the compact outcomes and diffs only.
          Do not read raw child transcripts unless explicitly necessary.
          Produce a final integration recommendation.
```

### 6.2 JS風DSLを残す場合

将来的にはPi風DSLを使ってもよい。
ただし、JSをそのまま実行せず、AST whitelistからIRに変換する。

許可するprimitive:

- `agent(prompt, opts)`
- `parallel([...])`
- `pipeline(items, ...stages)`
- `phase(title)`
- `log(message)`
- `budget.reserve(...)`

禁止するもの:

- arbitrary `fs`
- arbitrary `child_process`
- network direct access
- `Date.now()` / `Math.random()` など非決定性
- dynamic import
- eval
- unbounded loop

---

## 7. Reasoning Effort設計

### 7.1 Codex版ではeffortを一級制御にする

Claude Codeはモデルとeffortを動的に切り替えられる。
Codexでも `model` だけではなく、`reasoning_effort` をworkflow DSLに必ず入れる。

理由:

- scan系は深く考えさせるより速さが重要
- 実装は中〜高effortが必要
- architecture / review / synthesisは最高effortが効く
- すべてを最高effortにすると遅く高い
- すべてを低effortにすると統合品質が落ちる

### 7.2 推奨routing

| task種別 | model | reasoning_effort | worktree | fork_turns |
|---|---|---:|---|---|
| repo scan / file map | fast | low | read_only | none |
| issue triage | fast | low〜medium | read_only | none |
| implementation | coding | high | isolated | none or small N |
| localized fix | coding | medium〜high | isolated | small N |
| security review | strongest | high〜xhigh | read_only | none |
| architecture review | strongest | xhigh | read_only | none |
| final synthesis | strongest | xhigh | read_only | none |
| same-context branch exploration | parent model | parent effort | isolated/read_only | all |

### 7.3 Full fork時の制約を設計に反映

Codex nativeでfull forkする場合:

```yaml
mode: fork
fork_turns: all
# model/reasoning_effort overrideはしない
```

モデルやeffortを変える場合:

```yaml
mode: subagent
fork_turns: none
model_profile: strongest
reasoning_effort: xhigh
```

または外部runnerで別processにする。

```bash
codex exec \
  --json \
  -m gpt-5.4 \
  -c model_reasoning_effort="xhigh" \
  -C .codex-flow/worktrees/review_01 \
  --output-schema schemas/review.schema.json \
  -o .codex-flow/results/review_01.md \
  "$(cat .codex-flow/prompts/review_01.md)"
```

### 7.4 値は固定しすぎない

`reasoning_effort` の受理値はCodex CLI / provider / model設定に依存しうる。
runner側では以下のように扱う。

- DSL上は `low`, `medium`, `high`, `xhigh` などをprofile名として扱う
- 実際のCodex config値へmappingする
- 起動前にvalidationする
- unsupportedなら明示的にfailする

例:

```yaml
reasoning_profiles:
  low:
    codex_config: low
  medium:
    codex_config: medium
  high:
    codex_config: high
  xhigh:
    codex_config: xhigh
```

---

## 8. Worktree Isolation設計

### 8.1 なぜ必須か

大量並列agentに同じcheckoutをwriteさせると、以下が起きる。

- 同じfileを同時編集
- test/build artifact衝突
- lock file衝突
- git index破損
- agent同士が相手の未完成変更を読んで誤判断

そのため、write taskは基本的にworktree分離する。

### 8.2 worktree構成

```text
repo/
  .codex-flow/
    run-2026-05-30-001/
      workflow.yaml
      state.json
      prompts/
        implement_auth.md
      logs/
        implement_auth.jsonl
      results/
        implement_auth.json
        implement_auth.md
      diffs/
        implement_auth.patch
      worktrees/
        implement_auth/
        implement_billing/
        implement_tests/
```

### 8.3 worker起動

```bash
git worktree add \
  .codex-flow/run-001/worktrees/implement_auth \
  -b codex-flow/implement_auth \
  HEAD

codex exec \
  --json \
  -m "$MODEL" \
  -c model_reasoning_effort="$EFFORT" \
  -C ".codex-flow/run-001/worktrees/implement_auth" \
  --output-schema "schemas/patch_result.schema.json" \
  -o ".codex-flow/run-001/results/implement_auth.md" \
  "$(cat .codex-flow/run-001/prompts/implement_auth.md)" \
  > ".codex-flow/run-001/logs/implement_auth.jsonl"

git -C .codex-flow/run-001/worktrees/implement_auth diff \
  > .codex-flow/run-001/diffs/implement_auth.patch
```

### 8.4 merge方針

- disjoint write scopeなら自動apply候補
- conflictしたらintegration agentへ渡す
- integration agentはraw transcriptではなく以下だけ読む
  - patch
  - structured result
  - test output summary
  - blocker

---

## 9. Don’t Peek / Artifact設計

### 9.1 原則

子agentの全transcriptを親agentに読ませない。

理由:

- context爆発
- 間違った中間思考の汚染
- prompt injection混入
- token/cost増大
- synthesis品質低下

### 9.2 保存するもの

```text
logs/<task>.jsonl          # raw event stream。通常は親に渡さない
results/<task>.json        # schema-validated outcome
results/<task>.md          # short final text
artifacts/<task>/...       # test output, screenshots, reports
patches/<task>.patch       # code diff
```

### 9.3 親に渡すもの

```json
{
  "task_id": "implement_auth",
  "status": "success",
  "changed_files": ["src/auth/session.ts", "test/auth/session.test.ts"],
  "tests_run": ["npm test -- session.test.ts"],
  "test_status": "passed",
  "diff_path": ".codex-flow/run-001/diffs/implement_auth.patch",
  "summary": "Session refresh handling was fixed and tests were added.",
  "blockers": []
}
```

### 9.4 raw logを読む条件

raw JSONL transcriptを読むのは例外扱い。

読む条件:

- workerがschema違反で失敗
- blocker reasonが不足
- security issue疑い
- reproduce不能
- final synthesis agentが明示的に要求し、runnerが許可

---

## 10. Progress UI設計

Claude Code級の体験にするには、runnerがprogress surfaceを持つ必要がある。

### 10.1 表示すべき情報

- workflow name
- run id
- current phase
- phase count
- active agents
- queued agents
- completed agents
- failed agents
- elapsed time
- token/cost概算
- model/effort分布
- worktree数
- blocker一覧

### 10.2 表示例

```text
Codex Workflow: auth-refactor
Run: 2026-05-30-001

Phase 2/4: Implement
Agents: 12 running / 38 done / 3 failed / 7 queued

running:
  implement_auth_refresh     coding high   03:12
  implement_session_tests    coding high   02:44
  review_security_headers    strong xhigh  01:08

failed:
  implement_oauth_callback   conflict with src/auth/oauth.ts

artifacts:
  .codex-flow/run-001/results/
```

### 10.3 Slack向け表示

Slackでは詳細表を長文で出すより、要約を箇条書きにする。

```text
☀ Codex workflow: auth-refactor
▫ phase: Implement 2/4
▫ agents: 12 running / 38 done / 3 failed / 7 queued
▫ effort: low 16 / high 31 / xhigh 13
▫ blockers: oauth_callback conflict
▫ artifacts: .codex-flow/run-001/
```

---

## 11. Runnerの内部アルゴリズム

### 11.1 Task schema

```ts
type Task = {
  id: string
  phase: string
  depends_on: string[]
  role: string
  model: string
  reasoning_effort: string
  fork_turns?: 'none' | 'all' | `${number}`
  worktree: 'none' | 'read_only' | 'isolated'
  write_scope?: string[]
  prompt: string
  output_schema: string
  timeout_sec: number
  retries: number
  allow_failure: boolean
}
```

### 11.2 State machine

```text
pending
  -> runnable
    -> preparing_worktree
      -> running
        -> validating_output
          -> verifying
            -> succeeded
            -> failed
            -> needs_repair
```

### 11.3 Scheduling

1. workflow YAMLをparse
2. schema validation
3. phase DAG作成
4. dependencyが満たされたtaskをrunnableにする
5. global concurrencyとphase concurrencyを満たす範囲で起動
6. write taskならworktree作成
7. `codex exec` worker起動
8. JSONLをstream保存
9. final outputをschema検証
10. diff/test artifact収集
11. success/failをstateへ反映
12. fan-in phaseでcompact outcomeだけ渡す
13. final synthesis

---

## 12. Codex native multi_agent_v2の使い方

### 12.1 外部runnerとの役割分担

Codex native `multi_agent_v2` は使えるが、主runnerにはしない。

理由:

- worktree isolationはrunner側で持ちたい
- 100体以上のqueueは外側で制御したい
- cost/budget/retry/failure policyを一元管理したい
- full fork時のmodel/effort override制約がある

### 12.2 使う場面

worker内で小さく使う。

例:

```text
implementation worker
  -> spawn_agent security reviewer fork_turns:none model:strong effort:high
  -> spawn_agent test planner fork_turns:3 model:coding effort:medium
  -> wait_agent both
  -> integrate feedback
```

### 12.3 mapping

| Claude Code概念 | Codex native対応 | Codex外部runner対応 |
|---|---|---|
| Fork | `fork_turns: all` | 同一prompt/contextから別worker起動 |
| Subagent | `fork_turns: none` | isolated `codex exec` worker |
| Narrow context | `fork_turns: "N"` | promptにcompact contextを注入 |
| Team list | `list_agents` | runner state DB |
| Message | `send_message` | artifact/follow-up task生成 |
| Close | `close_agent` | process kill / task close |
| Dynamic Workflow | 一部のみ | runnerのphase/DAG/UI |
| Worktree isolation | 弱い | runnerが管理 |
| Model routing | 条件付き | `codex exec -m`で確実 |
| Effort routing | 条件付き | `-c model_reasoning_effort=...`で確実 |

---

## 13. 実装ロードマップ

### Phase 1: MVP

目的: Codex CLI workerを大量並列で安全に回す。

実装:

- `.codex-flow/workflow.yaml`
- YAML schema
- runner CLI: `codex-flow run workflow.yaml`
- worktree作成
- `codex exec --json` 起動
- JSONL保存
- `--output-schema`対応
- result validation
- final synthesis task

### Phase 2: Reasoning / model routing

実装:

- `model_profiles`
- `reasoning_profiles`
- taskごとのoverride
- phaseごとのdefault
- unsupported model/effort validation
- cost/token集計

### Phase 3: Progress UI

実装:

- terminal TUI
- Slack summary
- HTML dashboard optional
- phase/agent status
- failure/blocker表示

### Phase 4: native multi_agent_v2連携

実装:

- worker prompt内でnative toolsを使うtemplate
- `fork_turns` policy
- full fork時のoverride禁止をDSL validationに反映
- `list_agents` / `wait_agent` resultのartifact化

### Phase 5: MCP化

Codex parentから呼べるようにMCP server化する。

tools:

- `workflow_start`
- `workflow_status`
- `workflow_wait`
- `workflow_cancel`
- `workflow_collect`
- `workflow_open_artifact`

---

## 14. 最小MVPの疑似実装

### 14.1 runner command

```bash
codex-flow run .codex-flow/workflow.yaml
```

### 14.2 worker invocation template

```bash
run_task() {
  TASK_ID="$1"
  MODEL="$2"
  EFFORT="$3"
  WORKTREE="$4"
  SCHEMA="$5"
  PROMPT_FILE="$6"

  mkdir -p ".codex-flow/current/logs" ".codex-flow/current/results"

  codex exec \
    --json \
    -m "$MODEL" \
    -c model_reasoning_effort="$EFFORT" \
    -C "$WORKTREE" \
    --output-schema "$SCHEMA" \
    -o ".codex-flow/current/results/${TASK_ID}.md" \
    "$(cat "$PROMPT_FILE")" \
    > ".codex-flow/current/logs/${TASK_ID}.jsonl"
}
```

### 14.3 final synthesis prompt

```md
You are the synthesis agent.

Read only these compact artifacts:

- .codex-flow/current/results/*.json
- .codex-flow/current/diffs/*.patch
- .codex-flow/current/test-summaries/*.json

Do not read raw worker JSONL logs unless a result explicitly marks itself as incomplete.

Return:

1. What changed
2. Which tasks succeeded
3. Which tasks failed
4. Merge/conflict risks
5. Tests run
6. Recommended next action
```

---

## 15. 設計上の注意点

### 15.1 arbitrary JS workflowは避ける

PiはJS workflowが自然だが、Codex版でmodel-written JSをそのまま実行するのは危険。

最初はYAML/JSON IR。
JS風DSLを使う場合もAST whitelist必須。

### 15.2 full-history forkにモデル切替を期待しない

Codex nativeではfull-history fork時に `model` / `reasoning_effort` / `agent_type` override不可。

モデル/effort切替が必要なら外部runner workerにする。

### 15.3 raw transcript fan-in禁止

大規模化の最大の罠。
全agent transcriptをsynthesisに入れると、品質もcostも壊れる。

### 15.4 write scopeを必ず持つ

各workerに `write_scope` を渡す。
範囲外編集はrunner側で検出してfailまたはreviewに回す。

### 15.5 failure policyを明示

各taskに以下を持たせる。

- `allow_failure`
- `retries`
- `timeout_sec`
- `on_conflict`
- `on_schema_error`

---

## 16. 最終提案

CodexでClaude Code Dynamic Workflows級にするなら、実装方針は以下。

1. **外部runnerを作る**
   - Codex本体に全部やらせない
   - DAG / phase / queue / UI / artifact / worktreeを管理

2. **Codex CLIをworker primitiveにする**
   - `codex exec --json --output-schema -C -o`
   - taskごとに `-m` と `reasoning_effort` を指定

3. **reasoning_effortを一級パラメータにする**
   - Codex版では特に重要
   - scanはlow、実装はhigh、review/synthesisはxhigh

4. **native multi_agent_v2は局所fan-outに使う**
   - `fork_turns: none` = Subagent
   - `fork_turns: all` = Fork
   - `fork_turns: "N"` = narrow context
   - full fork時のoverride制約を守る

5. **Don’t Peekを守る**
   - raw transcriptは保存するが親に読ませない
   - structured outcomeだけfan-in

6. **worktree isolationを標準にする**
   - write taskは原則isolated worktree
   - conflictはintegration phaseで扱う

この構成なら、CodexでもClaude CodeのDynamic Workflowsに近い「大量agent・phase進行・動的model/effort・安全なworktree分離・compact synthesis」の体験を作れる。
