# 设计说明

状态：Python 模块重构；本地材料与 Docker 替身验证，真实镜像/NPU/CAModel 待验收。

## 范围与运行条件

工具消费用户准备的本地材料，制作 NPU 或仿真镜像，并输出报告。镜像制作与运行配置分为两个命令：build.py 只构建镜像，prepare_runtime.py 为已有镜像生成 Compose、可写 HOME 和容器账号副本。两者都不启动业务容器。下载、上传、宿主机驱动安装、设备分配、业务代码编译和算子验证由使用方负责。

宿主机仅依赖 Python 3.9+ 标准库和 Docker CLI/Buildx；无需安装 Python 包。容器采用 Ubuntu 22.04、amd64、Python 3.10。Bash 仅用于容器内安装与供应方环境加载，不在 Python 中通过 shell=True 执行命令。

## 模块边界

两个入口只分派命令，不实现业务：`build.py`、`prepare_runtime.py`。

| 模块 | 单一职责 | 修改或替换场景 |
| --- | --- | --- |
| `cli.py` | argparse 参数、环境默认值、退出码和信号边界 | CLI 形式调整 |
| `config.py` | BuildConfig/RuntimeConfig 数据对象、参数格式和框架基础版本一致性 | 参数规则变化 |
| `materials.py` | 固定目录定位、精确文件选择、材料校验和清单 | 目录布局或包名规则变化 |
| `toolkits.py` | 从 Toolkit 文件名识别 CANN 版本并选择唯一安装器 | Toolkit 文件命名规则变化 |
| `chips.py` | 将 SoC 具体型号或数字系列解析为唯一 ops 安装包 | 型号匹配策略变化 |
| `wheels.py` | 将 Torch/NPU 完整或基础版本解析为唯一的兼容 wheel | wheel 文件名、版本匹配策略变化 |
| `simulation.py` | 镜像内替换 CAModel 运行库、建立链接并生成环境脚本 | 仿真初始化步骤变化；独立标准库模块 |
| `python_deps.py` | 镜像内读取安装元数据、提取 CANN 依赖及记录包清单 | 声明式依赖处理；独立标准库模块 |
| `archives.py` | ZIP 安全校验及解压 | 压缩包格式处理变化；宿主机/容器共用 |
| `image.py` | 自动生成构建 ID；strict 下根据内容生成指纹 | 自动 tag 或指纹规则变化 |
| `context.py` | 临时构建上下文；仅 strict 复制后校验哈希 | 材料传入 Docker 的方式变化 |
| `docker.py` | Docker CLI 执行、日志流、基础镜像检查和临时容器 | 更换容器后端 |
| `reporting.py` | 计划、下载指导和构建报告 | 日志/报告格式变化 |
| `builder.py` | 按阶段协调镜像构建和构建报告 | 构建步骤顺序变化 |
| `accounts.py` | UID/GID 校验和容器账号副本转换 | 用户身份方案变化 |
| `compose.py` | 固定 Compose 结构的纯文本渲染 | 运行描述格式变化 |
| `runtime.py` | 检查运行资源、暂存和发布运行配置 | 运行配置生成流程变化 |
| `errors.py` | 可展示的错误与退出状态 | 统一错误边界 |

依赖方向：入口 → CLI → 工作流 → 专项模块。专项模块不导入 CLI 或工作流；`compose` 不访问 Docker/磁盘，`image` 不执行命令，`accounts` 不读取宿主机账号库。构建/运行工作流通过 `backend` 工厂接收 Docker 适配器，便于替换及独立测试；不引入插件注册器、泛化框架或第三方 SDK。

ZIP 与初始化模块仅依赖标准库，构建时按 `scripts/archives.py`、`scripts/simulation.py` 暂存到上下文，通过现有 Dockerfile 的脚本 COPY 进入镜像。strict 材料检查与容器解压使用同一份实现，源码仅在 strict 下参与内容指纹。

## 输入契约

唯一材料根为 `--materials-root`（默认 `./materials`），其下固定三个目录：

```text
ROOT/
├── cann/       # Toolkit 和匹配 SoC 的 ops .run
├── torch/      # 精确版本、cp310、x86_64 的两份 wheels
└── camodel/    # 主包、_config.zip、可选 init.sh/env.sh/check.sh
```

每个根目录保存一套材料，不额外嵌套版本、SoC 或架构。不同组合选择不同根目录。移除旧布局和 `--cann-root`、`--torch-root`、`--camodel-dir`，不读取旧的 CAModel 目录环境变量。不递归、不逐级回退；精确文件参数覆盖对应默认查找路径。

SoC 由 chips 模块从所选 CANN 版本、linux/x86_64 的 ops 文件名解析，忽略型号大小写。先精确匹配；没有精确候选且请求为纯数字型号时，可匹配紧随字母后缀的具体型号，例如 950 → 950dt/950pr，不匹配 9500。多个候选告警并停止，通过完整 --soc 或 --ops 文件明确选择；--strict-soc 禁用回退。解析后的具体型号用于计划、manifest 和内容指纹；tag 优先保留输入型号。CAModel 包配对仍按其独立输入契约检查，不推断型号兼容性。

Torch/NPU 在 cp310/x86_64 wheel 中先精确匹配；没有精确候选时，基础版本 X.Y.Z 可匹配 `.postN`、`.postN.devN`、`+local` 及其组合，不匹配其他基础版本、rc 或独立 dev 包。例如 2.7.1 → 2.7.1.post5.dev20261111。显式完整后缀仍严格匹配。唯一候选解析为文件中的完整版本；多个候选打印 WARNING 和路径后停止，不选最新、不交互等待。通过完整版本或精确 wheel 路径明确选择，也可用 `--strict-versions` 禁用基础版本回退。

配置模块检查输入格式；材料定位前保存 requested_components，随后依次从 Toolkit、ops、wheel 文件名识别 CANN 版本、SoC 和框架完整版本，并写回实际构建配置。型号/版本参数可省略；唯一候选直接使用，多候选告警停止。解析后检查 Torch/NPU 基础版本一致性，Toolkit 与 ops 必须同 CANN 版本。tag 的每个字段优先使用对应输入值，只有未输入时才使用实际解析值；manifest 同时记录 requested_* 和实际值。Docker 参数、安装检查和内容指纹使用实际值，输入简写不参与内容指纹，因此同一材料可以有不同简写 tag，但 strict 指纹保持一致。

材料缺失由共享错误格式列出组件、期望值、搜索位置、可见候选和修复参数。CAModel 缺少配对文件时明确指出主包/配置包及对应文件名。缺失与不匹配均依据选中材料报告，不维护固定版本组合名单。

仿真默认扫描当前 `camodel/` 的 `*ESLMODEL*.zip`，需要一对 `x86_64_ESLMODEL_<model>_<version>.zip` 和同名 `_config.zip`。例如 `x86_64_ESLMODEL_Ascend950DT_123A1.zip` 及其配置包。多套材料时报错，可显式重复 `--camodel-archive` 选择一对。配对校验不推断仿真包与 CANN/SoC 的兼容关系。

ZIP 仅在 `--strict` 下进行宿主机预检，包括目录元数据、路径、类型、合并后的命名空间及所有成员 CRC。普通构建直接暂存安装包，不打开 ZIP。所有包在镜像内直接解压到 `/opt/CAModel/`，解压时仍检查路径，允许共享目录，拒绝重复文件、文件/目录冲突、符号链接和路径穿越；读取本身会校验 CRC，不额外全量解压扫描。

内置 simulation 模块在镜像内查找 CANN `x86_64-linux/simulator/<soc_version>/lib/libruntime_camodel.so`，默认使用活动 CANN 安装目录及解析后的 SoC（允许 Ascend 前缀别名）。通过唯一的 `libnpu_drv_camodel.so` 定位 CAModel 库目录，复制替换运行库、创建两个相对软链接，并在同一目录生成 set_env.sh。路径不唯一或缺失立即报错；目录和型号可显式配置。

set_env.sh 固定 ASCEND_DEVICE_ID=0；ESL_HARDWARE_VERSION 默认 0x1000，由 --esl-hardware-version / ASCEND_DEV_ESL_HARDWARE_VERSION 配置。ESL_SOC_VERSION 为 Ascend950DT 这样的型号字符串，由 --esl-soc-version / ASCEND_DEV_ESL_SOC_VERSION 配置，仅用于生成 export，不参与运行库目录选择。CANN simulator 按独立的 --simu-soc / ASCEND_DEV_SIMU_SOC 匹配；未指定时使用材料解析后的 SoC。--soc 仍负责选择 ops 包，显式 --simu-soc 不改变 ops 的选择。未显式配置 ESL_SOC_VERSION 时，导出匹配到的目录名。库目录置于 LD_LIBRARY_PATH 首位且重复加载去重。生成的 /etc/ascend/camodel-env.sh 指向该脚本，由公共环境入口在可选 env.sh 之后加载。初始化设置写入只读输入 settings.json，参与 manifest 和镜像指纹，宿主机不读取镜像内路径。

外部 `init.sh` 改为可选扩展，在内置初始化后、已加载 CANN/仿真环境的 `/opt/CAModel` 下执行。不根据 ZIP 中同名脚本自动执行初始化。`env.sh` 可选，`check.sh` 必须显式启用。扩展/自检不下载内容，作为用户提供的受信任代码在构建中执行。

## 构建流程与资源

1. CLI 解析，配置对象校验；正常构建建立报告目录。
2. 材料模块定位并解析型号与 wheel 完整版本，生成输入清单；解析后检查框架基础版本一致性。只有 strict 才计算内容哈希并执行 ZIP 预检，普通 check 和普通构建都不扫描内容。
3. Docker 适配器检查本地 context、Engine builder、基础镜像架构和不可变 ID。
4. 镜像模块生成名称，报告模块记录参数、命名模式与校验状态；strict 才记录材料哈希。
5. 上下文模块暂存选定输入，仅 strict 再次核对哈希。
6. Docker 适配器执行 buildx --load --pull=false，逐块输出日志。
7. strict 再次确认基础镜像未移动；用未启动容器导出包清单。
8. 成功后发布 image-ref.txt，失败阶段写入 result.txt。运行配置由另一个命令单独生成，其结果不影响构建报告。

所有临时目录和容器使用上下文管理器清理；SIGINT/SIGTERM 经过退出边界触发 finally。失败记录退出码与阶段，保留构建日志。不执行 Docker 全局 prune，不使用业务容器执行检查。

默认 `--check` / `--check --files-only` 使用快速模式，只定位材料并检查文件属性与命名，不读取文件内容或 ZIP 元数据。两者都显示按实际版本生成的短 tag；前者额外检查 Docker，后者不访问 Docker。--check --strict 才计算完整构建指纹，镜像身份和上下文模块仅在 strict 下要求全部材料具备内容哈希。

实际构建默认不计算或比对哈希，不执行 ZIP 预检，直接复制并安装；只有 `--strict` 启用内容扫描与暂存比对。不生成空的或伪造的 materials.sha256，报告明确记录 integrity_validation=skipped/strict。strict 不影响版本模糊匹配。

短 tag 只包含目标、CANN、SoC 和 Torch/NPU 版本。每个字段优先使用用户输入（包括环境变量），未输入才从材料补齐；输入 2.7.1 则名称保留 2.7.1，输入完整 post/dev 日期则保留完整值。不附加 py310、amd64 或构建 ID，不提供自定义 tag。同一组命名字段对应同一个 tag，重新构建会更新该引用。构建身份单独记录在 manifest 和镜像标签中：普通构建使用随机 UUID（identity_mode=build-id），strict 使用完整 SHA-256（identity_mode=content-sha256）。哈希包含实际参数、输入内容、容器脚本和基础镜像 ID，不包含输入简写、本地材料路径、基础镜像别名、报告路径、缓存与显示选项。在线依赖变化仍可能影响镜像内容。

## 镜像内部

沿用一个多 target Dockerfile：`system-deps → cann → cann-only/torch-install → dev-common → npu/simulation`。仿真无需先构建 NPU 镜像；共有层复用缓存。原始安装材料通过只读 RUN mount 消费，不写入最终镜像层。

公共环境入口兼容 CANN 的 set_env.sh，恢复调用者的 nounset 状态，避免重复加载。--mirror-url（或 ASCEND_DEV_MIRROR_URL）统一指定镜像源，默认 http://mirrors.tools.huawei.com，APT/pip 分别追加 /ubuntu、/pypi/simple。pip 源写入 /etc/pip.conf，HTTP 源同时配置 trusted-host，所有当前/未来用户共享，运行期仍遵循 pip 标准覆盖规则。仅 strict 校验编译器、核心版本、CPU Torch 和普通用户可读性，不导入 torch_npu，不用硬件可用性作为构建条件。STRICT 构建参数传入共享层，控制安装器显式 --check 和安装后验证；不写入运行期 ENV。

Python 依赖没有固定开发工具包名单，也没有统一 numpy<2 限制。python_deps 在 CANN 安装前记录 Python 包版本及 Requires-Dist，安装后加载 CANN 环境，再提取新增/变更包的声明。原始依赖表达式写入 /etc/ascend/cann-requirements.txt，由 pip 处理版本范围、extras 和环境条件。Torch wheel 自身依赖通过正常 pip 安装解析；后续补齐 CANN 声明及用户 --pip-package 时约束已选 Torch 版本。没有元数据的依赖由用户显式补充，不猜测包名。

scripts 中保留各安装阶段的 install-system/install-cann/install-torch、公共收尾 finish-image、CAModel 初始化 prepare-simulation、运行入口 entrypoint/shell-env，以及仅 strict 调用的 verify-image。它们均有调用用途；移除预装开发包、固定 NumPy 上限和 verify-image 中的清单记录代码。普通构建仍通过 python_deps 的 inventory 动作记录包清单，仿真初始化后再刷新，记录过程不触发验证。

## 运行配置与权限

`prepare_runtime.py` 通过 --image 接收已有本地镜像的名称或 ID，通过本地镜像标签识别目标。仿真和 NPU 的 Compose 均固定以 root（0:0）运行；另外按当前 UID/GID 和 developer 用户名准备账号记录，供显式切换身份时使用。仅支持本地 Docker，账号复制按检查得到的镜像 ID 进行。

BuildConfig 与 RuntimeConfig 分别服务两个入口。builder 不导入运行配置模块，不接收代码、账号、设备或运行子网参数；运行配置命令独立接收镜像名称或 ID，无需报告文件，检查代码、账号和运行资源，再按本地镜像的不可变 ID 复制账号文件。构建机器无需具备 NPU 设备，运行配置在目标服务器执行。运行参数不参与镜像指纹。

`accounts` 从未启动容器复制 passwd/group，保留 root 等系统账号，仅替换指定非 root UID 记录；复用已有主组或新增 ascend-GID。冲突报错，不复制 shadow，不读写宿主机账号库。--uid/--gid/--user 仅配置该账号记录，不改变 Compose 的 root 运行身份；不在入口引入身份切换或递归 chown。

`runtime` 准备资源与私有暂存目录；所有校验和账号准备成功后，发布只读账号副本及 Compose，保留 HOME。NPU 检查字符设备、实际 GID 和驱动路径；仿真不需要设备。用户附加组通过 --group-add 显式配置。

prepare_runtime.py 通过 --output/-o 指定 Compose 文件路径，默认调用目录下的 compose.yaml；自动创建父目录，home/identity 放在文件旁。自定义文件名用于发布配置及打印启动命令；同一父目录中的配置共用 HOME 和账号副本，独立环境使用不同目录。

两个目标统一使用显式 IPAM 配置的项目 bridge 网络，默认子网 192.168.240.0/24。prepare_runtime.py 的 --runtime-subnet 可指定其他私有 IPv4 CIDR，不参与镜像指纹。工具不扫描或修改宿主机路由；使用方核对目标网络并为同时运行的项目指定不同子网。已有网络修改地址池时需先 down 再生成配置并启动。

`compose` 使用固定 schema 写入具体镜像、用户、设备、路径；单引号转义 YAML，$$ 避免 Compose 插值。长格式 bind mount 禁止自动创建源路径。无环境文件、无环境变量配置依赖、无第三方 YAML 库。

## 验证边界

标准库 unittest 覆盖 CLI、平铺目录、配对与安全检查、稳定命名、上下文变化、Docker 调用/失败清理、账号转换、Compose 和环境加载。Docker 由命令替身模拟，不表示真实安装或硬件功能已验证。完整使用流程与参数以 README 和 --help 为准。
