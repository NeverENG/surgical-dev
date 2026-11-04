# surgical-dev

用于**执行已确定方案**的 Codex skill。在现有 Git 仓库里开发功能或修复问题时，用它管住改动范围、测试和交付；方案讨论不交给它。

## 执行时做什么

| 主题 | 执行时要想清楚 | 如何落地 |
| --- | --- | --- |
| 需求契约 | 谁调用、谁处理、什么结果算完成？ | 开工前读已有文档与测试，列出各部分职责、输入输出、异常、状态变化和验收结果。有歧义才追问；用户要求确认的决定先等确认。 |
| 改动边界 | 哪些文件和差异段确实服务于契约？ | 修改前记录工作区/暂存区基线；修改后用文件 SHA-256 和暂存区索引拦截越界改动（Git 跟踪、非忽略及明确列入的忽略文件）。允许文件逐段审阅、签核指纹；新文件改动前登记必要性。二进制差异须单独核验。 |
| 测试 | 哪种错误必须被抓住，预期从哪来？ | 先设计主路径、边界、失败/恢复、回归和跨层场景，再让测试与最小实现小步迭代。断言可观察结果；失败先定位根因，确认测试本身错了才改。详见[测试设计](references/testing.md)。 |
| 最小链路 | 不动基础架构，能否先跑通一次真实调用？ | 从入口到结果接通一条真实路径，再补失败分支；确需改基础架构时先说明影响，等用户决定。 |
| 代码职责 | 依赖方向是否清楚，客户端、元数据和业务规则是否混层？ | 沿用原有分层，职责各归其位，写够用的实现；不为解耦制造无用抽象，也不夹带无关重构。 |
| 文档事实 | 变更后哪里能查到当前行为？ | 对已有架构/功能文档做最小同步；不新建执行流水账，过程留在 Git，CHANGELOG 只做索引。 |
| 用户体验 | 成功、失败与恢复在实际入口是什么样？ | 走通用户或调用方的真实路径，检查成功反馈、错误提示、恢复办法；界面任务在可行时验证实际渲染和交互。 |

闸门能自动发现越界**文件**，不能靠哈希判断同一文件中某段改动是否无关；逐段审阅是签核的一部分。无关改动不交付。

## 使用

安装到 Codex 的 skills 目录：

```sh
git clone https://github.com/NeverENG/surgical-dev.git ~/.codex/skills/surgical-dev
```

在仓库任务中直接调用，例如：

```text
$surgical-dev 在这个仓库修复“保存配置后没有结果提示”。沿用现有架构；成功时给出确认，失败时说明原因，原有读取行为不能退化。先列验收场景和职责，有歧义再问我。
```

skill 会在修改前建立基线，结束时运行测试、展示差异并执行范围签核。闸门脚本位于 `scripts/scope_gate.py`，提供 `start`、`extend`、`check` 三个命令。完整测试跑不了或存在原有失败时，会报告实际结果，不把局部通过说成全部通过。

## 参考

- [Superpowers：TDD 与测试质量](https://github.com/obra/superpowers/tree/main/skills/test-driven-development)：测试先能识别错误，再证明行为正确。
- [Superpowers：系统调试](https://github.com/obra/superpowers/tree/main/skills/systematic-debugging)、[完成前验证](https://github.com/obra/superpowers/tree/main/skills/verification-before-completion)：先找根因，用新鲜的测试结果支撑交付结论。
- [Anthropic：Web App Testing](https://github.com/anthropics/skills/tree/main/skills/webapp-testing)：有界面时验证真实渲染与操作，而不只看代码。

## 许可

[Apache License 2.0](LICENSE)。
