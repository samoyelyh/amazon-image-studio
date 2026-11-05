---
name: queue-inspection
description: 查询同组织共享队列或当前用户的任务进度，不暴露同事图片及提示词。
---

查询排队情况选择 business.read_shared_queue。
需要本会话具体任务时选择 business.current_jobs，由服务端限定当前会话的Job。
只使用服务端实际状态。工具不可用时报告错误，不编造预计等待时间。
队列摘要不是素材访问授权，不得据此下载同事图片。
