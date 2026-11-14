# surgical-dev

精准优秀不会出错的执行手，测试先行，提前构建架构范围，通过 CAS SHA256 拦截不应该修改的部分。
当修改到设计相关架构部分调整或触及到边界未提及的情况及时上报，由高级 Agent 或者 工程师处理
保证代码在架构方案确定以后执行对应的效果。
用于**用户要求开工、基础架构和方案已定的执行阶段**。仅询问、讨论或评估方案时，即使提到本 skill，也不启动开发或修改文件；开工后按约定范围写代码与测试，必要时同步已有文档。架构讨论留给其他流程。

## 执行时做什么

| 主题 | 执行时要想清楚 | 如何落地 |
| --- | --- | --- |
| 方案交接 | 本次目标、职责和大致改动范围是否已定？ | 读取已有文档或对话中的方案；只追问阻碍执行的歧义，不重复申请开工。 |
| 上下文契约 | 逻辑是否接到真实入口、已有实现是否重复、结果有没有被消费？ | 动手前沿调用链找现有实现；完成后从调用方核对响应、文件或界面状态及副作用，不只检查修改过的函数。 |
| 改动范围 | 实际改动是否服务于本次契约？ | 修改前按方案范围记录工作区基线；交付时自动比对。范围外文件解释必要性或撤回；同文件无关差异逐段剔除。无需逐文件预登记或签指纹。 |
| 测试 | 哪种错误必须被抓住测试先行，先设计对应测试可能场景再开始开工 | 先设计主路径、相关边界、失败和回归，再小步写测试与实现。断言可观察结果；失败先查根因，确认测试自身错了才改。详见[测试设计](references/testing.md)。 |
| 最小链路 | 本次任务的测试是否全部通过？ | 沿既定架构完成最小真实链路，以本次任务测试全绿为跑通标准。端到端在最后测，或交用户验收。 |
| 架构职责 | 是否触及共享契约、跨模块职责或基础 core 模型？ | 只暂停依赖该决定的部分，交给架构讨论；独立部分继续，模块内 DTO/实现正常推进。 |
| 文档事实 | 行为变化后，哪里描述当前功能？ | 对已有架构/功能文档最小同步；开发过程留在 Git，CHANGELOG 只做索引。 |
| 用户体验 | 成功、失败和恢复对用户是什么样？ | 检查实际入口、反馈、错误提示与恢复路径；界面任务有条件时验证真实交互。 |
| 交付汇报 | 没看代码的人能否对照场景读懂变化？ | 用纯文本标签和空行分节，不依赖 Markdown 粗体、标题、表格等渲染。先说入口、职责、调用链及为何要改；同一场景下分别写改前、改后、作用；已验证、待验收、下一步各自成行。复杂流程可用简短文字或伪代码，不用空话填满版面。 |

闸门对 Git 跟踪、非忽略文件及明确列入的忽略文件做基线比对，能指出越界文件；同文件改动是否相关仍由 agent 审阅，哈希不判断代码意图。

## 使用

安装到 Codex 的 skills 目录：

```sh
git clone https://github.com/NeverENG/surgical-dev.git ~/.codex/skills/surgical-dev
```

基础架构和执行方案已确认后，在仓库任务中调用，例如：

```text
$surgical-dev 在这个仓库修复“保存配置后没有结果提示”。沿用现有架构；成功时给出确认，失败时说明原因，原有读取行为不能退化。先列验收场景和职责，有歧义再问我。
```

skill 会处理基线与范围核对，无须你手动签指纹。闸门脚本位于 `scripts/scope_gate.py`，只提供 `start` 和 `check`：

```sh
python3 ~/.codex/skills/surgical-dev/scripts/scope_gate.py start --repo /path/to/repo --scope src/profile/ --scope tests/profile/
python3 ~/.codex/skills/surgical-dev/scripts/scope_gate.py check --state <上一步输出的状态目录>
# 只有出现必要的范围外改动时才附加：--explain 'src/common/http.py=本次调用方错误反馈所必需'
```

本次任务测试全绿即为实现跑通；仓库其他测试或尚未由用户完成的端到端验收，分别报告实际状态。审查由用户另行安排，不是 skill 的自动步骤。开发完毕不自动提交、推送或提 PR；Git 交付操作按用户明确指令执行。

## 参考

- [Superpowers：TDD 与测试质量](https://github.com/obra/superpowers/tree/main/skills/test-driven-development)：测试先能识别错误，再证明行为正确。
- [Superpowers：系统调试](https://github.com/obra/superpowers/tree/main/skills/systematic-debugging)、[完成前验证](https://github.com/obra/superpowers/tree/main/skills/verification-before-completion)：先找根因，用新鲜的测试结果支撑交付结论。
- [Anthropic：Web App Testing](https://github.com/anthropics/skills/tree/main/skills/webapp-testing)：有界面时验证真实渲染与操作，而不只看代码。

## 许可

[Apache License 2.0](LICENSE)。
