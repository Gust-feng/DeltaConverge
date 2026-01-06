# 说明

> 此版本为复现测评数据专门准备，存在不少BUG和性能问题，需要稳定版本请移步[main](https://github.com/Gust-feng/DeltaConverge/)分支

测评数据以[greptile](https://www.greptile.com/benchmarks)提供的基准测试为准，为了确保能够准确复现测评需遵循以下注意事项：

* 使用深度求索提供的`Deepseek-V3.2`，部分第三方渠道提供的模型不够稳定
* [sentry PR 6](https://github.com/ai-code-review-evaluation/sentry-greptile/pull/5)的代码变更达到`106`个文件，官方模型仅支持`128K`上下文，对于此情况，选用硅基流动等第三方平台提供`Deepseek-V3.2`模型。
* 为确保系统自动解析PR链接，尽量`Clone`  PR链接的仓库，而不是源仓库

***更多信息详见[如何优雅的进行一次测评](etc/存档/V2.9.5预览版使用说明.md)***
