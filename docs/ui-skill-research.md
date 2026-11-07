# UI设计skill调研与第二版采用记录

调研日期：2026-11-06。背景：本人认为第一版UI“AI味道太重”，未批准。目标是改进三页设计，不增加业务运行时、模型或云服务。

## 候选及选择

Star为查询时GitHub API瞬时值，只反映关注度，不代表质量认证或视觉验收。

| 候选/来源 | 仓库Star | 本轮查阅 | 适用与限制 | 决定 |
|---|---:|---|---|---|
| [Anthropic frontend-design](https://github.com/anthropics/skills/tree/ca45fc496a3436251f191354091d557da31c15b5/skills/frontend-design) | 187,808（整个skills仓库） | 完整SKILL.md及许可 | 指导从用途制定视觉方向，明确警惕暖色底/衬线展示字/英文眉题/装饰箭头等默认模板；不是成品组件或审美保证 | **本轮采用并安装**，配合项目skill |
| [Impeccable](https://github.com/pbakaus/impeccable/tree/c3bb418ee38ee49a6b999b7752c1368f3123a2bd/.agents/skills/impeccable) | 104,058 | README、完整入口SKILL.md与文件目录 | 区分Operate/Read，含critique/audit等工作流；现版本含上下文引擎/启动器，较本次有限样稿改版范围更广 | 保留候选；未安装或执行引擎，未声称完成它的工作流 |
| [UI UX Pro Max](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill/tree/b7d5353e0130feb8c5574ef1251f8a1db1873ccb) | 145,761 | README及公开skill说明 | 样式/配色/UX检索资料广；对本轮问题仍需人工选择，不能靠增加风格库解决模板感 | 保留候选，未安装/运行 |

同时查询了openai/skills的.curated目录，本次未发现更直接针对现有界面去模板化的独立设计skill；现有Figma类skill主要服务设计文件/组件工作流，本轮无需引入Figma。

## 实际安装与使用

- 官方skill-installer安装`anthropics/skills`的`skills/frontend-design`，固定commit：`ca45fc496a3436251f191354091d557da31c15b5`。
- 本机位置：`C:/Users/25311/.codex/skills/frontend-design/`，保留原SKILL.md与Apache-2.0许可；本轮已经读取并用于设计，宿主自动发现从下一轮开始可用。
- 项目skill `skills/personalkb-ui-design/`继续维护审核门槛、引用、演示隔离、设计确认及生产接入边界，修正首版过早锁定暖底/墨绿的偏好。
- 不安装新的前端框架、字体网络服务或生产依赖；不宣称skill安装即能消除主观模板感。

## 从skill转为本项目的设计决策

第二版采用[设计简报](ui-redesign-v2-brief.md)：日常操作/阅读工具，使用中性灰白工作区、系统中文无衬线字体、紧凑顶栏和可扫描列表；正文/审核分区、问答来源证据保留。删去无功能英文眉题、标语和过大展示留白。技术原名中的英文不删。

先看三页渲染结果是否匹配真实使用，再验交互和无障碍，不以“通过检查”替代本人审美反馈。按[V201–V208](ui-redesign-v2-test-cases.md)验证，第二版另址交付，第一版保留对照；仍须本人确认后才能统一实施正式UI。
