# 设计说明

状态：Python 模块重构；本地材料与 Docker 替身验证，真实镜像/NPU/CAModel 待验收。

## 范围与运行条件

工具消费用户准备的本地材料，制作 NPU 或仿真镜像，并输出报告。运行配置入口生成 Compose、可写 HOME 和容器账号副本，不启动业务容器。下载、上传、宿主机驱动安装、设备分配、业务代码编译和算子验证由使用方负责。

宿主机仅依赖 Python 3.9+ 标准库和 Docker CLI/Buildx；无需安装 Python 包。容器采用 Ubuntu 22.04、amd64、Python 3.10。Bash 仅用于容器内安装与供应方环境加载，不在 Python 中通过 shell=True 执行命令。

## 模块边界

两个入口只分派命令，不实现业务：`build.py`、`prepare_runtime.py`。

| 模块 | 单一职责 | 修改或替换场景 |
| --- | --- | --- |
| `cli.py` | argparse 参数、环境默认值、退出码和信号边界 | CLI 形式调整 |
| `config.py` | 构建数据对象和纯参数校验 | 参数规则、配套版本变化 |
| `materials.py` | 固定目录定位、精确文件选择、材料校验和清单 | 目录布局或包名规则变化 |
| `chips.py` | 将 SoC 具体型号或数字系列解析为唯一 ops 安装包 | 型号匹配策略变化 |
| `wheels.py` | 将 Torch/NPU 完整或基础版本解析为唯一的兼容 wheel | wheel 文件名、版本匹配策略变化 |
| `simulation.py` | 镜像内替换 CAModel 运行库、建立链接并生成环境脚本 | 仿真初始化步骤变化；独立标准库模块 |
| `archives.py` | ZIP 安全校验及解压 | 压缩包格式处理变化；宿主机/容器共用 |
| `image.py` | 根据参数、输入哈希、基础镜像 ID 计算镜像身份 | 自动 tag 或指纹规则变化 |
| `context.py` | 临时构建上下文和复制后哈希校验 | 材料传入 Docker 的方式变化 |
| `docker.py` | Docker CLI 执行、日志流、基础镜像检查和临时容器 | 更换容器后端 |
| `reporting.py` | 计划、下载指导和构建报告 | 日志/报告格式变化 |
| `builder.py` | 按阶段协调构建流程 | 构建步骤顺序变化 |
| `accounts.py` | UID/GID 校验和容器账号副本转换 | 用户身份方案变化 |
| `compose.py` | 固定 Compose 结构的纯文本渲染 | 运行描述格式变化 |
| `runtime.py` | 检查运行资源、暂存和发布运行配置 | 运行配置生成流程变化 |
| `errors.py` | 可展示的错误与退出状态 | 统一错误边界 |

依赖方向：入口 → CLI → 工作流 → 专项模块。专项模块不导入 CLI 或工作流；`compose` 不访问 Docker/磁盘，`image` 不执行命令，`accounts` 不读取宿主机账号库。构建/运行工作流通过 `backend` 工厂接收 Docker 适配器，便于替换及独立测试；不引入插件注册器、泛化框架或第三方 SDK。

ZIP 与初始化模块仅依赖标准库，构建时按 `scripts/archives.py`、`scripts/simulation.py` 暂存到上下文，通过现有 Dockerfile 的脚本 COPY 进入镜像。宿主机材料检查与容器解压使用同一份实现，源码参与输入指纹。

## 输入契约

唯一材料根为 `--materials-root`（默认 `./materials`），其下固定三个目录：

```text
ROOT/
├── cann/       # Toolkit 和匹配 SoC 的 ops .run
├── torch/      # 精确版本、cp310、x86_64 的两份 wheels
└── camodel/    # 主包、_config.zip、可选 init.sh/env.sh/check.sh
```

每个根目录保存一套材料，不额外嵌套版本、SoC 或架构。不同组合选择不同根目录。移除旧布局和 `--cann-root`、`--torch-root`、`--camodel-dir`，不读取旧的 CAModel 目录环境变量。不递归、不逐级回退；精确文件参数覆盖对应默认查找路径。

SoC 由 chips 模块从所选 CANN 版本、linux/x86_64 的 ops 文件名解析，忽略型号大小写。先精确匹配；没有精确候选且请求为纯数字型号时，可匹配紧随字母后缀的具体型号，例如 950 → 950dt/950pr，不匹配 9500。多个候选告警并停止，通过完整 --soc 或 --ops 文件明确选择；--strict-soc 禁用回退。解析后的具体型号参与计划、manifest、tag 和指纹；CAModel 包配对仍按其独立输入契约检查，不推断型号兼容性。

Torch/NPU 在 cp310/x86_64 wheel 中先精确匹配；没有精确候选时，基础版本 X.Y.Z 可匹配 `.postN`、`.postN.devN`、`+local` 及其组合，不匹配其他基础版本、rc 或独立 dev 包。例如 2.7.1 → 2.7.1.post5.dev20261111。显式完整后缀仍严格匹配。唯一候选解析为文件中的完整版本；多个候选打印 WARNING 和路径后停止，不选最新、不交互等待。通过完整版本或精确 wheel 路径明确选择，也可用 `--strict-versions` 禁用基础版本回退。

配置模块先检查输入格式和 Torch/NPU 基础版本一致性。材料定位调用 chips/wheel 模块后，将解析出的具体型号、完整版本写回本次构建配置；先完成材料合法性检查，再检查软件配套记录，避免材料缺失被配套提示遮住。后续 tag、指纹、manifest、Docker 参数及安装检查使用实际解析值；匹配开关和输入简写不参与指纹，因此相同文件得到相同名称。开发版本仍需 --allow-unverified，不因允许文件名匹配而自动登记为已验证组合。

材料缺失由共享错误格式列出组件、期望值、搜索位置、可见候选和修复参数。CAModel 缺少配对文件时明确指出主包/配置包及对应文件名。配套诊断则单独标注缺少的是组合记录、完整组合、不同的组件及参考版本，不把未收录等同于缺失文件或已确认不兼容。

仿真默认扫描当前 `camodel/` 的 `*ESLMODEL*.zip`，需要一对 `x86_64_ESLMODEL_<model>_<version>.zip` 和同名 `_config.zip`。例如 `x86_64_ESLMODEL_Ascend950DT_123A1.zip` 及其配置包。多套材料时报错，可显式重复 `--camodel-archive` 选择一对。配对校验不推断仿真包与 CANN/SoC 的兼容关系。

ZIP 默认只预检目录元数据、路径、类型及合并后的命名空间；允许共享目录，拒绝重复文件、文件/目录冲突、符号链接和路径穿越。`--strict` 才在宿主机扫描所有成员的 CRC。所有包直接解压到 `/opt/CAModel/`，保留包内层级及文件执行位，不套包名目录；解压读取本身会校验 CRC，因此不再额外执行一遍全量解压预检。

内置 simulation 模块在镜像内查找 CANN `x86_64-linux/simulator/<soc_version>/lib/libruntime_camodel.so`，默认使用活动 CANN 安装目录及解析后的 SoC（允许 Ascend 前缀别名）。通过唯一的 `libnpu_drv_camodel.so` 定位 CAModel 库目录，复制替换运行库、创建两个相对软链接，并在同一目录生成 set_env.sh。路径不唯一或缺失立即报错；目录和型号可显式配置。

set_env.sh 固定 ASCEND_DEVICE_ID=0；ESL_HARDWARE_VERSION 默认 0x1000，由 --esl-hardware-version / ASCEND_DEV_ESL_HARDWARE_VERSION 配置。ESL_SOC_VERSION 为 Ascend950DT 这样的型号字符串，由 --esl-soc-version / ASCEND_DEV_ESL_SOC_VERSION 配置，并用于 CANN simulator 目录选择；未指定时按 --soc 匹配并使用实际目录名。库目录置于 LD_LIBRARY_PATH 首位且重复加载去重。生成的 /etc/ascend/camodel-env.sh 指向该脚本，由公共环境入口在可选 env.sh 之后加载。初始化设置写入只读输入 settings.json，参与 manifest 和镜像指纹，宿主机不读取镜像内路径。

外部 `init.sh` 改为可选扩展，在内置初始化后、已加载 CANN/仿真环境的 `/opt/CAModel` 下执行。不根据 ZIP 中同名脚本自动执行初始化。`env.sh` 可选，`check.sh` 必须显式启用。扩展/自检不下载内容，作为用户提供的受信任代码在构建中执行。

## 构建流程与资源

1. CLI 解析，配置对象校验；正常构建建立报告目录。
2. 材料模块定位并解析型号与 wheel 完整版本，校验材料并生成输入清单；随后配置模块校验配套记录。普通 check 的清单只含源路径/逻辑路径，SHA-256 为空；strict check 和实际构建才计算内容哈希。
3. Docker 适配器检查本地 context、Engine builder、基础镜像架构和不可变 ID。
4. 镜像模块计算名称，报告模块记录参数、指纹和哈希。
5. 上下文模块暂存选定输入并再次核对哈希。
6. Docker 适配器执行 buildx --load --pull=false，逐块输出日志。
7. 再次确认基础镜像未移动，用未启动容器导出包清单；只有全部成功才发布 image-ref.txt。

所有临时目录和容器使用上下文管理器清理；SIGINT/SIGTERM 经过退出边界触发 finally。失败记录退出码与阶段，保留构建日志。不执行 Docker 全局 prune，不使用业务容器执行检查。

默认 `--check` / `--check --files-only` 使用快速模式，不扫描大文件哈希或 ZIP 内容 CRC。前者检查 Docker 后显示镜像名待计算，后者不访问 Docker；`--check --strict` 才能计算最终 tag。文件/ZIP 元数据安全检查两种模式都保留，输出明确标注 fast/strict。镜像身份和上下文模块拒绝没有内容哈希的输入，防止快速检查元数据被误用于最终 tag。

实际构建仍始终计算内容哈希并复制后复核，这是自动命名的输入契约；`--strict` 对实际构建额外启用 ZIP CRC 预扫描。检查强度开关不参与指纹，也不影响版本模糊匹配开关。

名称包含目标、CANN、SoC、完整 Torch/NPU 版本、py310、amd64 和 SHA-256 前 12 位；不提供自定义 tag。哈希包含参数、输入内容、容器脚本和基础镜像 ID，不包含本地材料路径、基础镜像别名、报告路径、缓存与显示选项。在线依赖变化仍可能影响镜像内容。

## 镜像内部

沿用一个多 target Dockerfile：`system-deps → cann → cann-only/torch-install → dev-common → npu/simulation`。仿真无需先构建 NPU 镜像；共有层复用缓存。原始安装材料通过只读 RUN mount 消费，不写入最终镜像层。

公共环境入口兼容 CANN 的 set_env.sh，恢复调用者的 nounset 状态，避免重复加载。pip 源写入 /etc/pip.conf，所有当前/未来用户共享，运行期仍遵循 pip 标准覆盖规则。构建校验编译器、核心版本、CPU Torch 和普通用户可读性，不导入 torch_npu，不用硬件可用性作为构建条件。

## 运行配置与权限

`prepare_runtime.py` 从构建报告读取镜像引用，通过本地镜像标签识别目标，默认使用当前 UID/GID 和 developer 用户名。仅支持本地 Docker，账号复制按检查得到的镜像 ID 进行。

`accounts` 从未启动容器复制 passwd/group，保留系统账号，仅替换指定 UID 记录；复用已有主组或新增 ascend-GID。冲突报错，不复制 shadow，不读写宿主机账号库。容器以目标身份直接运行，不在入口引入 root 初始化、降权或递归 chown。

`runtime` 准备资源与私有暂存目录；所有校验和账号准备成功后，发布只读账号副本及 Compose，保留 HOME。NPU 检查字符设备、实际 GID 和驱动路径；仿真不需要设备。用户附加组通过 --group-add 显式配置。

`compose` 使用固定 schema 写入具体镜像、用户、设备、路径；单引号转义 YAML，$$ 避免 Compose 插值。长格式 bind mount 禁止自动创建源路径。无环境文件、无环境变量配置依赖、无第三方 YAML 库。

## 验证边界

标准库 unittest 覆盖 CLI、平铺目录、配对与安全检查、稳定命名、上下文变化、Docker 调用/失败清理、账号转换、Compose 和环境加载。Docker 由命令替身模拟，不表示真实安装或硬件功能已验证。完整使用流程与参数以 README 和 --help 为准。
