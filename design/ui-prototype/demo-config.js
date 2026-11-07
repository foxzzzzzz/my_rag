/* 演示资料、预设问题和默认范围；均为虚构示例，不连接正式数据。 */
export const items=[
{id:'attention',title:'V01：知识库问答实践',type:'视频',topic:'工作方法',status:'已批准',score:99,date:'2026-10-28',summary:'知识库资料检索与问答流程的静态展示。',body:['知识库问答通常从检索相关资料开始，再结合检索结果组织回答。','引用提供回看资料的入口，便于核对回答是否有依据。'],evidence:'静态演示证据：回答应结合资料并保留可追溯的引用。'},
{id:'notes',title:'OpenManus：开源智能体框架',type:'HTML',topic:'知识管理',status:'已批准',score:100,date:'2026-10-21',summary:'开源智能体框架的资料阅读演示。',body:['智能体框架可以将任务、工具与执行过程组织在一起。','阅读框架资料时，可以关注工具调用方式、运行边界与使用条件。'],evidence:'静态演示网页证据：关注框架的工具调用与运行边界。'},
{id:'reading',title:'smolagents：轻量智能体工具',type:'HTML',topic:'阅读',status:'已批准',score:100,date:'2026-10-15',summary:'轻量智能体工具的资料阅读演示。',body:['轻量智能体工具提供组织任务和工具调用的方式。','核对资料时，应结合原文确认具体能力与限制。'],evidence:'静态演示网页证据：关注工具调用及其限制。'},
{id:'review',title:'建立每周回顾的节奏',type:'视频',topic:'工作方法',status:'待审核',score:null,date:'2026-11-02',summary:'一份待核对的整理稿，讨论如何回顾进展并调整下一周的重点。',body:['每周回顾可以从已经完成的事情开始，再看哪些事项仍需要关注。','这份演示整理稿尚待核对，请结合证据检查内容是否准确，再分别记录评分和批准。'],evidence:'演示视频片段：讲者提到每周回顾与下一步计划。'}];
export const examples={answered:'知识库问答如何使用资料？',unanswered:'火星上明天的天气如何？',scope:'已批准资料'};

/* 审核演示门槛，保持与项目默认规则一致。 */
export const approvalThreshold = 98;
